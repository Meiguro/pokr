import difflib
import re
import numpy

class TimestampRecognizer(object):
    '''
    Extract play time from stream.
    '''

    def __init__(self, settings, debug=False):
        self.timestamp_settings = settings['timestamp']
        self.col_to_char = self.timestamp_settings['characterMap']
        self.debug = debug
        self.timestamp = '0d0h0m0s'
        self.timestamp_s = 0

    def handle(self, data):
        [x, y] = self.timestamp_settings['position']
        [w, h] = self.timestamp_settings['size']
        timestamp = data['frame'][y:y+h, x:x+w]
        col_sum = (timestamp > 150).sum(axis=0)  # Sum bright pixels in each column
        col_str = (col_sum *.5 + ord('A')).astype(numpy.int8).tostring()  #
        strings = re.split(r'A*', col_str)  # Segment by black columns
        if self.debug:
            print(strings)
            import cv2
            cv2.imshow('timestamp', timestamp)
            cv2.waitKey(0)
        try:
            result = self.convert(strings)
            days, hours, minutes, seconds = (int(x) for x in re.split('[dhms:]', result) if len(x) > 0)
            self.timestamp = result
            self.timestamp_s = ((days * 24 + hours) * 60 + minutes) * 60 + seconds
        except (ValueError, IndexError):
            pass    # invalid timestamp (ocr failed)
        finally:
            data['timestamp'] = self.timestamp
            data['timestamp_s'] = self.timestamp_s

    def convert(self, strings):
        col_to_char = self.col_to_char

        def match(x):
            if x in col_to_char:
                return col_to_char[x]
            close = difflib.get_close_matches(x, col_to_char, cutoff=.6)
            return col_to_char[close[0]]

        return ''.join(match(x) for x in strings if x)
