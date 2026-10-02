import numpy as np

from src.optical import cloud_fraction


def test_cloud_fraction_ignores_nodata():
    scl = np.array([[0, 0, 6, 6], [6, 9, 8, 6]])     # 0 nodata, 6 water, 8/9 cloud
    assert cloud_fraction(scl) == 2 / 6
    assert cloud_fraction(np.zeros((2, 2), int)) == 1.0
