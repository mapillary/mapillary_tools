pip install -r requirements.txt
pip install pyinstaller
pyinstaller --distpath dist\win --onefile --windowed mapillary_tools.spec 

mkdir publisih\win
xcopy dist\win\mapillary_tools.exe publish\win\

if %BRANCH_NAME% == "master" ( 
    aws s3 cp publish/win/mapillary_tools.exe s3://tools.mapillary.com/binary/win/mapillary_tools.exe
    )
else (
    echo "Will NOT publish branch $BRANCH_NAME. Only master is published to s3"
)
