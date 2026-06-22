import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline


class PipelineTests(unittest.TestCase):
    def test_srt_parse_clean_and_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.srt"
            path.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\n这是一个用于验证字幕清洗的完整句子。\n\n"
                "2\n00:00:02,000 --> 00:00:04,000\n这是一个用于验证字幕清洗的完整句子。\n\n"
                "3\n00:00:04,000 --> 00:00:06,000\n谢谢观看\n\n"
                "4\n00:00:06,000 --> 00:00:09,000\n第二句话保留时间戳，也可以成为候选关键句。\n",
                encoding="utf-8",
            )
            segments = pipeline.parse_srt_vtt(path)
            cleaned_text, cleaned = pipeline.clean_segments(segments)
            summary, quotes = pipeline.reference_extract(cleaned_text, [])
            self.assertEqual(len(cleaned), 2)
            self.assertNotIn("谢谢观看", cleaned_text)
            self.assertTrue(summary)
            self.assertTrue(quotes)

    def test_metric_independent_srt_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.srt"
            pipeline.write_srt(path, [{"start": 1.25, "end": 2.5, "text": "测试"}])
            self.assertIn("00:00:01,250 --> 00:00:02,500", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
