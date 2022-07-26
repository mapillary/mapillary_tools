$OS="win"

mkdir -Force dist

# build
python3 -m pip uninstall -y pyinstaller
git clone --depth=1 --branch v5.2 https://github.com/pyinstaller/pyinstaller.git pyinstaller_git
cd pyinstaller_git/bootloader
python3 ./waf all
git diff
cd ..
# Error: Building wheels requires the 'wheel' package. Please `pip install wheel` then try again.
python3 -m pip install wheel
python3 setup.py install
pyinstaller --version
pyinstaller --noconfirm --distpath dist\win mapillary_tools.spec
cd ..

# check
$SOURCE="dist\win\mapillary_tools.exe"
dist\win\mapillary_tools.exe --version
$VERSION_OUTPUT=dist\win\mapillary_tools.exe --version
$VERSION=$VERSION_OUTPUT.split(' ')[2]
$TARGET="dist\releases\mapillary_tools-$VERSION-$OS.exe"

# package
mkdir -Force dist\releases
Copy-Item "$SOURCE" "$TARGET"

# sha256
Get-FileHash $TARGET -Algorithm SHA256 | Select-Object Hash > "$TARGET.sha256.txt"

# summary
Get-ChildItem dist\releases
