$OS="win"

# build
mkdir -Force dist
Remove-Item -Recurse -Force -Confirm:$false dist\win
pyinstaller --noconfirm --distpath dist\win --onefile --windowed mapillary_tools.spec

# check
$SOURCE="dist\win\mapillary_tools.exe"
$VERSION_OUTPUT=dist\win\mapillary_tools.exe --version
$VERSION=$VERSION_OUTPUT.split(' ')[2]
$TARGET="dist\releases\mapillary_tools-$VERSION-$OS.exe"

# package
mkdir -Force dist\releases
Copy-Item "$SOURCE" "$TARGET"

# sha256
Get-FileHash $TARGET -Algorithm SHA256 | Select-Object Hash > "$TARGET.sha256"