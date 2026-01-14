const { useState, useEffect, useCallback } = React;

// ============ API Helpers ============
const API_BASE = '/api';

async function apiRequest(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
    });
    if (!response.ok) {
        throw new Error(`API Error: ${response.status}`);
    }
    return response.json();
}

// ============ Components ============

function StatusBadge({ status }) {
    const statusClass = `status-${status}`;
    const icon = {
        pending: 'bi-hourglass-split',
        running: 'bi-play-fill',
        paused: 'bi-pause-fill',
        completed: 'bi-check-circle-fill',
        cancelled: 'bi-x-circle-fill',
    }[status] || 'bi-question-circle';

    return (
        <span className={`status-badge ${statusClass}`}>
            <i className={`bi ${icon} me-1`}></i>
            {status}
        </span>
    );
}

function WorkerCard({ worker }) {
    const isRendering = worker.current_task_id !== null;
    const statusClass = isRendering ? 'worker-rendering' : 'worker-idle';

    return (
        <div className={`card mb-3 ${statusClass}`}>
            <div className="card-body">
                <div className="d-flex justify-content-between align-items-start">
                    <div>
                        <h5 className="card-title mb-1">
                            <i className="bi bi-pc-display me-2"></i>
                            {worker.worker_name}
                        </h5>
                        <small className="text-muted">
                            ID: {worker.worker_id}
                        </small>
                    </div>
                    <div>
                        {isRendering ? (
                            <span className="badge bg-info">
                                <i className="bi bi-gear-fill me-1"></i>Rendering
                            </span>
                        ) : (
                            <span className="badge bg-secondary">Idle</span>
                        )}
                    </div>
                </div>
                <hr className="my-2" style={{ borderColor: 'rgba(255,255,255,0.1)' }} />
                <div className="row g-2">
                    <div className="col-6">
                        <div className="d-flex align-items-center">
                            <i className="bi bi-cpu me-2 text-primary"></i>
                            <small>{worker.cpu_cores} cores</small>
                        </div>
                    </div>
                    <div className="col-6">
                        <div className="d-flex align-items-center">
                            <i className="bi bi-gpu-card me-2 text-success"></i>
                            <small className="text-truncate" style={{ maxWidth: '150px' }}>
                                {worker.gpu_name || 'Unknown'}
                            </small>
                        </div>
                    </div>
                </div>
                {worker.current_task_id && (
                    <div className="mt-2">
                        <small className="text-info">
                            <i className="bi bi-film me-1"></i>
                            Task: {worker.current_task_id.slice(0, 8)}...
                        </small>
                    </div>
                )}
            </div>
        </div>
    );
}

function JobCard({ job, onStart, onPause, onResume, onCancel }) {
    const [isExpanded, setIsExpanded] = useState(false);

    return (
        <div className="card mb-3">
            <div className="card-body">
                <div className="d-flex justify-content-between align-items-start mb-2">
                    <div className="flex-grow-1">
                        <h5 className="card-title mb-1">{job.name}</h5>
                        <small className="text-muted">
                            ID: {job.id.slice(0, 8)}...
                        </small>
                    </div>
                    <StatusBadge status={job.status} />
                </div>

                <div className="mb-3">
                    <div className="d-flex justify-content-between mb-1">
                        <small>Progress</small>
                        <small>{job.progress}%</small>
                    </div>
                    <div className="progress" style={{ height: '8px' }}>
                        <div
                            className="progress-bar bg-gradient"
                            style={{ width: `${job.progress}%` }}
                        ></div>
                    </div>
                </div>

                <div className="row g-2 mb-3">
                    <div className="col-6">
                        <small className="text-muted">
                            <i className="bi bi-film me-1"></i>
                            {job.completed_frames} / {job.total_frames} frames
                        </small>
                    </div>
                    <div className="col-6 text-end">
                        <small className="text-muted">
                            {Math.round(job.total_frames - job.completed_frames)} remaining
                        </small>
                    </div>
                </div>

                <div className="d-flex gap-2">
                    {job.status === 'pending' && (
                        <button
                            className="btn btn-success btn-sm flex-grow-1"
                            onClick={() => onStart(job.id)}
                        >
                            <i className="bi bi-play-fill me-1"></i>Start
                        </button>
                    )}
                    {job.status === 'running' && (
                        <>
                            <button
                                className="btn btn-warning btn-sm flex-grow-1"
                                onClick={() => onPause(job.id)}
                            >
                                <i className="bi bi-pause-fill me-1"></i>Pause
                            </button>
                            <button
                                className="btn btn-danger btn-sm flex-grow-1"
                                onClick={() => onCancel(job.id)}
                            >
                                <i className="bi bi-x-circle-fill me-1"></i>Cancel
                            </button>
                        </>
                    )}
                    {job.status === 'paused' && (
                        <>
                            <button
                                className="btn btn-success btn-sm flex-grow-1"
                                onClick={() => onResume(job.id)}
                            >
                                <i className="bi bi-play-fill me-1"></i>Resume
                            </button>
                            <button
                                className="btn btn-danger btn-sm flex-grow-1"
                                onClick={() => onCancel(job.id)}
                            >
                                <i className="bi bi-x-circle-fill me-1"></i>Cancel
                            </button>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}

function CreateJobModal({ show, onHide, onCreate }) {
    const [name, setName] = useState('');
    const [file, setFile] = useState(null);
    const [frameStart, setFrameStart] = useState(1);
    const [frameEnd, setFrameEnd] = useState(100);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!file) {
            setError('Please select a .blend file');
            return;
        }

        setLoading(true);
        setError(null);

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('name', name);
            formData.append('frame_start', frameStart);
            formData.append('frame_end', frameEnd);

            const result = await apiRequest('/jobs/create', {
                method: 'POST',
                body: formData,
                headers: {}, // Let browser set Content-Type for FormData
            });

            onCreate(result);
            setName('');
            setFile(null);
            setFrameStart(1);
            setFrameEnd(100);
            onHide();
        } catch (err) {
            setError('Failed to create job: ' + err.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className={`modal fade ${show ? 'show d-block' : ''}`} tabIndex="-1">
            <div className="modal-dialog modal-lg">
                <div className="modal-content">
                    <div className="modal-header">
                        <h5 className="modal-title">
                            <i className="bi bi-plus-circle me-2"></i>Create New Render Job
                        </h5>
                        <button type="button" className="btn-close btn-close-white" onClick={onHide}></button>
                    </div>
                    <form onSubmit={handleSubmit}>
                        <div className="modal-body">
                            {error && (
                                <div className="alert alert-danger">
                                    <i className="bi bi-exclamation-triangle me-2"></i>
                                    {error}
                                </div>
                            )}
                            <div className="mb-3">
                                <label className="form-label">Job Name (optional)</label>
                                <input
                                    type="text"
                                    className="form-control"
                                    placeholder="My Animation"
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                />
                            </div>
                            <div className="mb-3">
                                <label className="form-label">Blender File (.blend)</label>
                                <input
                                    type="file"
                                    className="form-control"
                                    accept=".blend"
                                    onChange={(e) => setFile(e.target.files[0])}
                                    required
                                />
                                <small className="text-muted">
                                    <i className="bi bi-info-circle me-1"></i>
                                    Resources will be automatically packed
                                </small>
                            </div>
                            <div className="row">
                                <div className="col-6">
                                    <label className="form-label">Start Frame</label>
                                    <input
                                        type="number"
                                        className="form-control"
                                        value={frameStart}
                                        onChange={(e) => setFrameStart(parseInt(e.target.value))}
                                        min="0"
                                        required
                                    />
                                </div>
                                <div className="col-6">
                                    <label className="form-label">End Frame</label>
                                    <input
                                        type="number"
                                        className="form-control"
                                        value={frameEnd}
                                        onChange={(e) => setFrameEnd(parseInt(e.target.value))}
                                        min="0"
                                        required
                                    />
                                </div>
                            </div>
                            <div className="mt-2">
                                <small className="text-muted">
                                    Total frames: <strong>{Math.max(0, frameEnd - frameStart + 1)}</strong>
                                </small>
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button type="button" className="btn btn-secondary" onClick={onHide}>
                                Cancel
                            </button>
                            <button type="submit" className="btn btn-primary" disabled={loading}>
                                {loading ? (
                                    <>
                                        <span className="spinner-border spinner-border-sm me-2"></span>
                                        Creating...
                                    </>
                                ) : (
                                    <>
                                        <i className="bi bi-plus-circle me-1"></i>Create Job
                                    </>
                                )}
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    );
}

function StatsCard({ icon, label, value, color }) {
    return (
        <div className="card stats-card">
            <div className="card-body text-center">
                <i className={`bi ${icon} fs-2 text-${color} mb-2`}></i>
                <div className="stat-value">{value}</div>
                <div className="text-muted">{label}</div>
            </div>
        </div>
    );
}

function ConnectionStatus({ connected }) {
    return (
        <div className="connection-status">
            <div className={`status-dot ${connected ? 'connected' : 'disconnected'}`}></div>
            <span>{connected ? 'Connected' : 'Disconnected'}</span>
        </div>
    );
}

// ============ Main App ============

function App() {
    const [jobs, setJobs] = useState([]);
    const [workers, setWorkers] = useState([]);
    const [wsConnected, setWsConnected] = useState(false);
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [loading, setLoading] = useState(true);

    // Fetch initial data
    useEffect(() => {
        async function fetchData() {
            try {
                const [jobsData, workersData] = await Promise.all([
                    apiRequest('/jobs'),
                    apiRequest('/workers'),
                ]);
                setJobs(jobsData);
                setWorkers(workersData);
            } catch (error) {
                console.error('Failed to fetch initial data:', error);
            } finally {
                setLoading(false);
            }
        }
        fetchData();
    }, []);

    // WebSocket connection
    useEffect(() => {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

        ws.onopen = () => {
            console.log('WebSocket connected');
            setWsConnected(true);
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected');
            setWsConnected(false);
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            setWsConnected(false);
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log('WebSocket update:', data);

            if (data.jobs) {
                setJobs(data.jobs);
            }
            if (data.workers) {
                setWorkers(data.workers);
            }
        };

        return () => {
            ws.close();
        };
    }, []);

    // Job control handlers
    const handleStartJob = async (jobId) => {
        try {
            await apiRequest(`/jobs/${jobId}/start`, { method: 'POST' });
        } catch (error) {
            console.error('Failed to start job:', error);
            alert('Failed to start job');
        }
    };

    const handlePauseJob = async (jobId) => {
        try {
            await apiRequest(`/jobs/${jobId}/pause`, { method: 'POST' });
        } catch (error) {
            console.error('Failed to pause job:', error);
            alert('Failed to pause job');
        }
    };

    const handleResumeJob = async (jobId) => {
        try {
            await apiRequest(`/jobs/${jobId}/resume`, { method: 'POST' });
        } catch (error) {
            console.error('Failed to resume job:', error);
            alert('Failed to resume job');
        }
    };

    const handleCancelJob = async (jobId) => {
        if (!confirm('Are you sure you want to cancel this job?')) return;
        try {
            await apiRequest(`/jobs/${jobId}/cancel`, { method: 'POST' });
        } catch (error) {
            console.error('Failed to cancel job:', error);
            alert('Failed to cancel job');
        }
    };

    const handleCreateJob = (result) => {
        console.log('Job created:', result);
        // Data will be updated via WebSocket
    };

    // Calculate stats
    const totalFrames = jobs.reduce((sum, job) => sum + job.total_frames, 0);
    const completedFrames = jobs.reduce((sum, job) => sum + job.completed_frames, 0);
    const runningJobs = jobs.filter(job => job.status === 'running').length;
    const activeWorkers = workers.length;

    return (
        <>
            {/* Navbar */}
            <nav className="navbar navbar-expand-lg sticky-top">
                <div className="container-fluid">
                    <a className="navbar-brand" href="#">
                        <i className="bi bi-film me-2"></i>WeRender
                    </a>
                    <div className="ms-auto">
                        <ConnectionStatus connected={wsConnected} />
                    </div>
                </div>
            </nav>

            {/* Main Content */}
            <div className="container-fluid py-4">
                {loading ? (
                    <div className="text-center py-5">
                        <div className="spinner-border text-primary" role="status">
                            <span className="visually-hidden">Loading...</span>
                        </div>
                        <p className="mt-3 text-muted">Loading dashboard...</p>
                    </div>
                ) : (
                    <>
                        {/* Stats Row */}
                        <div className="row g-3 mb-4">
                            <div className="col-md-3">
                                <StatsCard
                                    icon="bi-film"
                                    label="Total Frames"
                                    value={totalFrames}
                                    color="primary"
                                />
                            </div>
                            <div className="col-md-3">
                                <StatsCard
                                    icon="bi-check-circle-fill"
                                    label="Completed"
                                    value={completedFrames}
                                    color="success"
                                />
                            </div>
                            <div className="col-md-3">
                                <StatsCard
                                    icon="bi-play-fill"
                                    label="Running Jobs"
                                    value={runningJobs}
                                    color="info"
                                />
                            </div>
                            <div className="col-md-3">
                                <StatsCard
                                    icon="bi-pc-display"
                                    label="Active Workers"
                                    value={activeWorkers}
                                    color="warning"
                                />
                            </div>
                        </div>

                        {/* Jobs and Workers */}
                        <div className="row">
                            {/* Jobs Column */}
                            <div className="col-lg-8 mb-4">
                                <div className="card mb-3">
                                    <div className="card-header d-flex justify-content-between align-items-center">
                                        <h5 className="mb-0">
                                            <i className="bi bi-film me-2"></i>Render Jobs
                                        </h5>
                                        <button
                                            className="btn btn-primary btn-sm"
                                            onClick={() => setShowCreateModal(true)}
                                        >
                                            <i className="bi bi-plus-circle me-1"></i>New Job
                                        </button>
                                    </div>
                                    <div className="card-body">
                                        {jobs.length === 0 ? (
                                            <div className="text-center py-5 text-muted">
                                                <i className="bi bi-inbox fs-1 mb-3 d-block"></i>
                                                <p>No render jobs yet</p>
                                                <button
                                                    className="btn btn-primary btn-sm"
                                                    onClick={() => setShowCreateModal(true)}
                                                >
                                                    Create your first job
                                                </button>
                                            </div>
                                        ) : (
                                            jobs.map(job => (
                                                <JobCard
                                                    key={job.id}
                                                    job={job}
                                                    onStart={handleStartJob}
                                                    onPause={handlePauseJob}
                                                    onResume={handleResumeJob}
                                                    onCancel={handleCancelJob}
                                                />
                                            ))
                                        )}
                                    </div>
                                </div>
                            </div>

                            {/* Workers Column */}
                            <div className="col-lg-4 mb-4">
                                <div className="card mb-3">
                                    <div className="card-header">
                                        <h5 className="mb-0">
                                            <i className="bi bi-pc-display me-2"></i>Workers
                                        </h5>
                                    </div>
                                    <div className="card-body">
                                        {workers.length === 0 ? (
                                            <div className="text-center py-5 text-muted">
                                                <i className="bi bi-people fs-1 mb-3 d-block"></i>
                                                <p>No workers connected</p>
                                                <small className="text-muted">
                                                    Workers will appear here when they join the network
                                                </small>
                                            </div>
                                        ) : (
                                            workers.map(worker => (
                                                <WorkerCard key={worker.worker_id} worker={worker} />
                                            ))
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </>
                )}
            </div>

            {/* Create Job Modal */}
            <CreateJobModal
                show={showCreateModal}
                onHide={() => setShowCreateModal(false)}
                onCreate={handleCreateJob}
            />

            {/* Backdrop */}
            {showCreateModal && <div className="modal-backdrop fade show" style={{ zIndex: 1040 }}></div>}
        </>
    );
}

// Render app
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);