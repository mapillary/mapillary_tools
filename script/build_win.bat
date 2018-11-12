pip install -r requirements.txt
pip install pyinstaller
pyinstaller --distpath dist\win --onefile --windowed mapillary_tools.spec 

mkdir publisih\win

dir publish\

xcopy dist\win\mapillary_tools.exe publish\win\

dir publish\
