from mapillary_tools.gpmf import gpmf_parser


def test_simple():
    x = gpmf_parser.KLV.parse(b"DEMO\x02\x01\x00\x01\xff\x00\x00\x00")
    x = gpmf_parser.GPMFSampleData.parse(
        b"DEM1\x01\x01\x00\x01\xff\x00\x00\x00DEM2\x03\x00\x00\x01"
    )
