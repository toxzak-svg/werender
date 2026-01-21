# WeRender Release Process

This document outlines the process for creating and publishing WeRender releases.

## Prerequisites

- GitHub CLI (`gh`) installed and authenticated
- Python 3.10+ installed
- Write access to the WeRender repository
- PyPI account (if publishing to PyPI)

## Version Numbering

WeRender follows [Semantic Versioning](https://semver.org/):
- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality (backwards compatible)
- **PATCH**: Bug fixes (backwards compatible)
- **beta**: Pre-release for testing
- **rc**: Release candidate

Examples:
- `0.1.0` - Initial MVP release
- `0.2.0b0` - Beta release of version 0.2.0
- `0.2.0` - Stable release of version 0.2.0
- `0.2.1` - Bug fix release

## Pre-Release Checklist

Before creating a release, ensure:

- [ ] All features for the release are implemented
- [ ] All tests pass: `pytest`
- [ ] Code style checks pass: `ruff check .`
- [ ] Documentation is updated (README, CHANGELOG, User Guide)
- [ ] CHANGELOG.md is updated with version changes
- [ ] Version in `pyproject.toml` is updated
- [ ] No critical issues are open for this version
- [ ] Demo project (if applicable) is tested

## Release Steps

### 1. Update Version Number

Edit `pyproject.toml` and update the version:

```toml
[project]
version = "0.2.0"  # or 0.2.0b0 for beta, 0.2.0rc1 for release candidate
```

### 2. Update CHANGELOG.md

Add a new version section with all changes:

```markdown
## [0.2.0] - 2026-01-21

### Added
- New feature description
- Another new feature

### Changed
- Description of changed behavior

### Fixed
- Bug fix description

### Security
- Security improvement description
```

Update the Unreleased section to show what's planned for future versions.

### 3. Update Documentation

- Update README.md if there are new features or breaking changes
- Update User Guide if workflow changed
- Update Architecture docs if design changed
- Update any other relevant documentation

### 4. Install Build Tools

```bash
python -m pip install --upgrade build twine
```

### 5. Build the Package

```bash
python -m build
```

This creates:
- `dist/werender-<version>.tar.gz` - Source distribution
- `dist/werender-<version>-py3-none-any.whl` - Wheel distribution

### 6. Verify the Package

```bash
# Check package metadata
python -m twine check dist/*

# List wheel contents
python -m zipfile -l dist/werender-<version>-py3-none-any.whl
```

Ensure all expected files are included and no sensitive files are present.

### 7. Create GitHub Release

Create a draft release with GitHub CLI:

```bash
gh release create v<version> \
  --title "WeRender v<version>" \
  --notes "Draft release notes" \
  --draft
```

Or create detailed release notes in a file first:

```bash
# Create RELEASE_NOTES.md with detailed release notes
gh release edit v<version> --notes-file RELEASE_NOTES.md
```

### 8. Upload Package Assets

```bash
gh release upload v<version> \
  dist/werender-<version>-py3-none-any.whl \
  dist/werender-<version>.tar.gz
```

### 9. Review and Publish

1. Review the release on GitHub: https://github.com/toxzak-svg/werender/releases
2. Remove the `--draft` flag when ready to publish:
   ```bash
   gh release edit v<version> --draft=false
   ```
3. Or publish through the GitHub web UI

### 10. Publish to PyPI (Optional)

If you want to publish to PyPI:

```bash
# Test upload to TestPyPI first
python -m twine upload --repository testpypi dist/*

# If successful, upload to PyPI
python -m twine upload dist/*
```

Note: PyPI publishing requires:
- A PyPI account with API token
- The `werender` package name registered on PyPI
- For TestPyPI, the test package name may be different

### 11. Create Git Tag

```bash
git tag -a v<version> -m "Release v<version>"
git push origin v<version>
```

### 12. Update Development Branch

After release, update the development branch for the next version:

```bash
# Update pyproject.toml to next development version
# For example, after v0.2.0:
# version = "0.3.0.dev0" or "0.2.1.dev0"

# Commit and push
git add pyproject.toml
git commit -m "Bump version to 0.3.0.dev0"
git push
```

## Post-Release Tasks

- [ ] Announce release on GitHub Discussions
- [ ] Update any pinned issues or milestones
- [ ] Close completed milestones
- [ ] Create new milestone for next version
- [ ] Share on social media (Twitter, Reddit, Blender forums)
- [ ] Monitor for bug reports and issues
- [ ] Update project status in README if maturity changed

## Automated Release (Future)

Consider setting up automated releases using GitHub Actions:

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install build tools
        run: pip install build twine
      - name: Build package
        run: python -m build
      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: twine upload dist/*
```

## Troubleshooting

### Build Fails

- Check `pyproject.toml` syntax
- Ensure all dependencies are listed
- Verify Python version compatibility

### Twine Check Fails

- Check `README.md` and `pyproject.toml` metadata
- Ensure long description is valid reStructuredText
- Verify all required fields are present

### Package Missing Files

- Check `tool.hatch.build.targets.wheel` in `pyproject.toml`
- Ensure all necessary files are included in `packages` or `artifacts`
- Use `python -m zipfile -l` to inspect the wheel

### GitHub Release Issues

- Ensure tag exists locally and remotely
- Check GitHub CLI authentication: `gh auth status`
- Verify release name matches tag format (e.g., `v0.2.0`)

## Best Practices

1. **Test thoroughly** before release
2. **Start with draft releases** to review before publishing
3. **Test PyPI** before publishing to PyPI
4. **Keep CHANGELOG detailed** for users to understand changes
5. **Document breaking changes** clearly
6. **Use semantic versioning** consistently
7. **Tag releases in Git** for easy rollback if needed
8. **Announce releases** to the community
9. **Monitor feedback** after release
10. **Plan next version** roadmap after release

## Quick Reference

```bash
# Quick release sequence
python -m build
python -m twine check dist/*
gh release create v<version> --notes-file RELEASE_NOTES.md --draft
gh release upload v<version> dist/*
# Review and publish on GitHub UI
git tag -a v<version> -m "Release v<version>"
git push origin v<version>