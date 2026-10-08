"""完整标识的边界既保护编码扩展，也允许中文名称正常接续业务文字。"""
import re
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from identifier_aliases import complete_literal_pattern


class IdentifierBoundaries(unittest.TestCase):
    def test_chinese_name_after_source_number_is_complete(self):
        self.assertIsNotNone(re.search(complete_literal_pattern('测量点名称11'), '源系统1测量点名称11的数值'))

    def test_numeric_name_suffix_is_not_truncated(self):
        self.assertIsNone(re.search(complete_literal_pattern('测量点名称11'), '测量点名称111的数值'))

    def test_ascii_code_cannot_be_a_prefix_or_embedded_suffix(self):
        for text in ('PREFIXCODE_A', 'CODE_A.child', 'CODE_A#2', 'CODE_A&SUB'):
            self.assertIsNone(re.search(complete_literal_pattern('CODE_A'), text))
        self.assertIsNotNone(re.search(complete_literal_pattern('CODE_A'), '查看CODE_A。'))

if __name__ == '__main__':unittest.main(verbosity=2)
