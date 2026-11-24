"""提供一个可被 pytest 发现并直接通过的占位测试。"""

def test_dummy():
    print("Dummy test")
    assert True
