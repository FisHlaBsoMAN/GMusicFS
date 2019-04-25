import re

class Tools:

    @staticmethod
    def strip_text (string_from):
        """Format a name to make it suitable to use as a filename"""
        return re.sub('[^\w0-9_\.!?#@$ ]+', '_', string_from.strip())

