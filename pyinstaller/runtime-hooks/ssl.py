import os
import sys

if sys.platform == 'darwin':
    os.environ['SSL_CERT_FILE'] = os.path.join(sys._MEIPASS, 'lib', 'cacert.pem')