# Override the pyinstaller-hooks-contrib meta-hook that fails to import on
# webrtcvad-wheels. webrtcvad is a single C extension with no data files.
hiddenimports = []
datas = []
binaries = []
