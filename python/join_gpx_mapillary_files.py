import sys
import glob, os

'''
this scripts is a fast way to join a lot of GPX files downloaded from mapillary
if you use download_gpx_from_sequences.py , this is your second step for join 
all in just one file. 

use this script as: 

python join_gpx_mapillary_files.py [gpx_directory] [outputfile.gpx]

ex: python join_gpx_mapillary_files.py gpx_from_sequences salida.gpx

by danilo@lacosox.org
15/10/2015 

'''

HEAD_FILE="<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n \
           <gpx version=\"1.0\">\n \
           <name></name>\n \
           <trk>\n \
           <name/>\n \
           <number>1</number>\n"
          
FOOT_FILE="</trk>\n</gpx>"

if __name__ == '__main__':
    try:
        gpx_dir, output_file = sys.argv[1:3]  
    except:
        sys.exit("Usage: python %s files output_file.gpx" % sys.argv[0])
    
    files_to_join = glob.glob(os.path.join(gpx_dir,'*.gpx'))
    print("Found {0} GPX files to join".format(len(files_to_join)))
    
    final_file = open(output_file, 'w')
    final_file.write(HEAD_FILE)
    
    for file in files_to_join:
        try:
                gpx_read = open(file, 'r')
                gpx_file_txt=gpx_read.read()
                
                track_segment=gpx_file_txt[(gpx_file_txt.index('<trkseg>')):]
                track_segment=track_segment[:(track_segment.index('</trkseg>')+9)]+"\n"
                final_file.write(track_segment)
        except:
                print "Unexpected error:", sys.exc_info()[0]
                sys.exit("Probems in %s" % file)
           
    final_file.write(FOOT_FILE)
    final_file.close()
    print("done.")
    
