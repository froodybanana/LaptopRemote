import unittest

from laptopremote_agent import pipeline


class PipelineTests(unittest.TestCase):
    def test_launch_text_puts_the_encoder_between_convert_and_parse(self):
        text = pipeline.launch_text(9, 90, "192.0.2.10", 47801, 47802, "x264enc name=enc bitrate=8000")
        self.assertIn("pipewiresrc fd=9 path=90 ", text)
        self.assertIn("videoconvert name=live n-threads=2 ! x264enc name=enc bitrate=8000 ! h265parse", text)
        self.assertIn("udpsink host=192.0.2.10 port=47801 bind-port=47802", text)
