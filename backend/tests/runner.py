#!/usr/bin/env python3
"""
模块用途：集中运行 SafeMeds 后端测试并输出汇总结果。
SafeMeds Agent 测试运行器
=========================
运行全部单元测试并输出详细报告。

用法:
    python -m tests.runner              # 运行全部测试
    python -m tests.runner -v                           # 详细模式
    python -m tests.runner test_drug_recognition        # 仅运行特定模块
"""

import sys
import unittest

# 发现所有测试
loader = unittest.TestLoader()
suite = unittest.TestSuite()

# 加载全部 test_*.py
test_dir = __file__.rsplit("/", 1)[0] if "/" in __file__ else "tests"
all_tests = loader.discover(test_dir, pattern="test_*.py")

if len(sys.argv) > 1 and sys.argv[1] != "-v":
    # 仅运行指定模块
    suite.addTests(loader.loadTestsFromName(f"tests.{sys.argv[1]}"))
else:
    suite = all_tests

verbosity = 2 if "-v" in sys.argv else 1
runner = unittest.TextTestRunner(verbosity=verbosity)
result = runner.run(suite)

sys.exit(0 if result.wasSuccessful() else 1)
