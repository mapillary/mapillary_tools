from PyInstaller.compat import is_darwin

if (is_darwin):
    import certifi
    datas = [(certifi.where(), 'lib')]
