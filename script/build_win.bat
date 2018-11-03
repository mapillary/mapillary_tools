pip install -r requirements.txt
pip install pyinstaller
pyinstaller --distpath dist\win --onefile --windowed mapillary_tools.spec 

mkdir -p publish
mv dist\win publish\
