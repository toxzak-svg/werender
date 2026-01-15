bl_info = {
    "name": "WeRender Submitter",
    "author": "WeRender Team",
    "version": (0, 1, 0),
    "blender": (3, 0, 0),
    "location": "Properties > Render > WeRender",
    "description": "Submit render jobs to a remote WeRender Coordinator",
    "warning": "",
    "wiki_url": "",
    "category": "Render",
}

import bpy
import json
import socket
import threading
import requests
import shutil
import tempfile
import os
from pathlib import Path


# --- Properties ---

class WeRenderPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    hub_address: bpy.props.StringProperty(
        name="Hub Address",
        description="IP Address of the WeRender Hub/Coordinator",
        default="127.0.0.1",
    ) # type: ignore

    hub_port: bpy.props.IntProperty(
        name="Hub Port",
        description="Port of the WeRender Hub/Coordinator",
        default=8420,
        min=1024,
        max=65535,
    ) # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "hub_address")
        layout.prop(self, "hub_port")


class WeRenderSettings(bpy.types.PropertyGroup):
    job_name: bpy.props.StringProperty(
        name="Job Name",
        description="Name of the job (defaults to filename)",
        default="",
    ) # type: ignore

    auto_pack: bpy.props.BoolProperty(
        name="Pack Resources",
        description="Automatically pack external files into the .blend before uploading",
        default=True,
    ) # type: ignore
    
    status_message: bpy.props.StringProperty(
        name="Status",
        default="Ready",
    ) # type: ignore


# --- Operators ---

class WERENDER_OT_submit_job(bpy.types.Operator):
    """Submit the current scene to the WeRender Coordinator"""
    bl_idname = "werender.submit_job"
    bl_label = "Submit Job"
    
    def execute(self, context):
        # basic validation
        if not bpy.data.is_saved:
            self.report({'ERROR'}, "Please save the blend file first!")
            return {'CANCELLED'}

        prefs = context.preferences.addons[__name__].preferences
        settings = context.scene.werender_settings
        
        hub_url = f"http://{prefs.hub_address}:{prefs.hub_port}"
        
        # Start submission in a separate thread to avoid freezing UI
        thread = threading.Thread(target=self.submit_job_thread, args=(context, hub_url, settings.job_name, settings.auto_pack))
        thread.start()
        
        settings.status_message = "Submitting..."
        return {'FINISHED'}

    def submit_job_thread(self, context, hub_url, job_name, auto_pack):
        try:
            # 1. Create a temporary copy of the blend file
            if not bpy.data.filepath:
                 # Should be caught by execute(), but just in case
                self.report_status(context, "Error: File not saved")
                return

            original_path = bpy.data.filepath
            
            with tempfile.NamedTemporaryFile(suffix=".blend", delete=False) as tmp_file:
                temp_path = tmp_file.name
            
            # Save a copy 
            # We use save_copy to avoid modifying the user's open file state (except for packing)
            # BUT, if we want to pack, we might need to modify the current file or open the copy.
            # Easiest valid way: 
            #  - Save current file (user should have saved)
            #  - Make a copy or save_copy
            #  - If packing needed:
            #      - We can't easily pack a *copy* without opening it. 
            #      - So, let's use bpy.ops.file.pack_all() if checked, then save_copy, then unpack if desired? 
            #      - Safer: Let's assume the user wants to send *this* file. 
            #      - If "Pack Resources" is checked, we force a pack locally? No that's intrusive.
            #      - Better approach: Save Copy -> Open Copy (background) -> Pack -> Save -> Upload? Too complex.
            #      - Pragmatic approach: 
            #          If auto_pack is True:
            #             bpy.ops.file.pack_all()
            #          
            #          bpy.ops.wm.save_copy(filepath=temp_path)
            #          
            #          # Optionally undo the pack if we don't want to mess up user's file?
            #          # Actually, if the user explicitly checked "Pack Resources", they might accept it modifying their session.
            #          # Or we warn them.
            
            # For this MVP, let's just save_copy. If the user wants packed, they should pack it or we enable auto-pack which modifies session.
            
            # Let's try to be non-destructive:
            # We will use the 'compress' option on save_copy just in case, but actual resource packing requires ops.
            
            # NOTE: Accessing bpy.ops in a thread is unsafe! 
            # We must run blender operations in the main thread.
            # This logic flaw means we can't do heavy lifting in 'execute' without freezing, 
            # but we can't do bpy operations in a thread.
            # 
            # Correct Pattern: Do file ops in 'execute', then network ops in thread.
            
            pass # Logic moved to execute_blocking or handled before thread start.
            
        except Exception as e:
            print(f"Thread Error: {e}")

# We need to restructure to separate main-thread Blender ops from bg-thread Network ops.

class WERENDER_OT_submit_job_async(bpy.types.Operator):
    """Submit the current scene to the WeRender Coordinator"""
    bl_idname = "werender.submit_job_async"
    bl_label = "Submit Job"
    
    def execute(self, context):
        if not bpy.data.is_saved:
            self.report({'ERROR'}, "Please save the blend file first!")
            return {'CANCELLED'}
        
        settings = context.scene.werender_settings
        prefs = context.preferences.addons[__name__].preferences
        
        # 1. Prepare the file (Main Thread)
        # Create temp file
        import tempfile
        fd, temp_path = tempfile.mkstemp(suffix=".blend")
        os.close(fd)
        
        try:
            # Optional: Pack resources if requested
            # Note: This modifies the ACTIVE session. 
            if settings.auto_pack:
                bpy.ops.file.pack_all()
            
            # Save copy
            bpy.ops.wm.save_copy(filepath=temp_path)
            
            # Optional: Unpack if we want to restore? 
            # For now, let's leave it packed if the user asked for it, to avoid confusion.
            # Or assume "Pack Resources" implies "Pack properties for this submission only" which is hard.
            # Let's assume the user is okay with packing if they checked the box.
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to prepare file: {str(e)}")
            return {'CANCELLED'}

        # 2. Network Upload (Background Thread)
        hub_url = f"http://{prefs.hub_address}:{prefs.hub_port}"
        job_name = settings.job_name or bpy.path.basename(bpy.data.filepath)
        start_frame = context.scene.frame_start
        end_frame = context.scene.frame_end
        
        thread = threading.Thread(
            target=self.upload_thread, 
            args=(temp_path, hub_url, job_name, start_frame, end_frame)
        )
        thread.start()
        
        settings.status_message = "Uploading..."
        return {'FINISHED'}

    def upload_thread(self, file_path, hub_url, job_name, start, end):
        try:
            url = f"{hub_url}/api/jobs/create"
            
            with open(file_path, 'rb') as f:
                files = {'file': f}
                data = {
                    'name': job_name,
                    'frame_start': str(start),
                    'frame_end': str(end)
                }
                
                print(f"WeRender: Uploading to {url}...")
                response = requests.post(url, files=files, data=data, timeout=30)
                
            if response.status_code == 200:
                print("WeRender: Job submitted successfully!")
                self.update_status("Job Submitted!")
            else:
                print(f"WeRender: Failed. {response.status_code} - {response.text}")
                self.update_status(f"Failed: {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            self.update_status("Error: Connection Failed")
        except Exception as e:
            print(f"WeRender Error: {e}")
            self.update_status(f"Error: {str(e)[:20]}...")
        finally:
            # Cleanup temp file
            try:
                os.remove(file_path)
            except:
                pass

    def update_status(self, message):
        # Update the property in a thread-safe way? 
        # Writing to properties from a thread is generally "mostly safe" in recent Blender but can crash.
        # Best practice is to use a timer or just risk it for simple strings.
        # For this MVP, we will try direct assignment but wrap in a timer if needed.
        # Actually, let's just use a functional approach:
        
        def update():
            # Need to find the scene... 
            # Since we can't easily pass 'context' (it becomes invalid),
            # we rely on bpy.context.window_manager or similar if possible.
            # But here we only have the module scope.
            
            # Simple workaround: Just update the first scene's settings or active scene?
             if bpy.context and bpy.context.scene:
                bpy.context.scene.werender_settings.status_message = message
        
        # Schedule update on main thread
        bpy.app.timers.register(update, first_interval=0.1)


# --- Panel ---

class WERENDER_PT_panel(bpy.types.Panel):
    bl_label = "WeRender"
    bl_idname = "WERENDER_PT_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.werender_settings
        prefs = context.preferences.addons[__name__].preferences
        
        # Header / Status
        row = layout.row()
        row.label(text=f"Hub: {prefs.hub_address}:{prefs.hub_port}")
        
        box = layout.box()
        box.prop(settings, "job_name")
        box.prop(settings, "auto_pack")
        
        layout.separator()
        
        row = layout.row()
        row.prop(context.scene, "frame_start")
        row.prop(context.scene, "frame_end")
        
        layout.separator()
        
        row = layout.row()
        row.scale_y = 1.5
        row.operator("werender.submit_job_async", icon='RENDER_ANIMATION')
        
        if settings.status_message:
            row = layout.row()
            row.alignment = 'CENTER'
            row.label(text=settings.status_message)


# --- Registration ---

classes = (
    WeRenderPreferences,
    WeRenderSettings,
    WERENDER_OT_submit_job_async,
    WERENDER_PT_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.werender_settings = bpy.props.PointerProperty(type=WeRenderSettings)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    del bpy.types.Scene.werender_settings

if __name__ == "__main__":
    register()
