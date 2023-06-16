# build bootloaders
# to fix the virus false detection e.g. https://www.virustotal.com/gui/file/a2e8d8287f53e1691e44352b7fbc93038b36ad677d1faacfc1aa875de92af5a6
python3 -m pip uninstall -y pyinstaller
git clone --depth=1 --branch v5.12.0 https://github.com/pyinstaller/pyinstaller.git pyinstaller_git
cd pyinstaller_git/bootloader # pwd: ./pyinstaller_git/bootloader
python3 ./waf all
git diff
cd ..  # pwd: ./pyinstaller_git
# Error: Building wheels requires the 'wheel' package. Please `pip install wheel` then try again.
python3 -m pip install .
cd ..  # pwd: ./
