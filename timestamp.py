import difflib
import re
import time
import numpy

def format_timestamp(time=None, start_time=None):
    MINUTE = 60
    HOUR = 60 * MINUTE
    DAY = 24 * HOUR

    time = time or time.time()
    if start_time is not None:
        time -= start_time

    is_neg = time < 0
    time = abs(time)

    days = int(time / DAY)
    hours = int(time % DAY / HOUR)
    minutes = int(time % HOUR / MINUTE)
    seconds = int(time % MINUTE)

    return '{}{}d{}h{}m{}s'.format('-' if is_neg else '', days, hours, minutes, seconds)

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
        success = True
        try:
            result = self.convert(strings)
            days, hours, minutes, seconds = (int(x) for x in re.split('[dhms:]', result) if len(x) > 0)
            self.timestamp = result
            self.timestamp_s = ((days * 24 + hours) * 60 + minutes) * 60 + seconds
        except (ValueError, IndexError):
            success = False # invalid timestamp (ocr failed)
        finally:
            if success:
                data['timestamp'] = self.timestamp
                data['timestamp_s'] = self.timestamp_s
            elif 'start' in self.timestamp_settings:
                time_delta = int(time.time() - self.timestamp_settings['start'])
                data['timestamp'] = format_timestamp(time_delta)
                data['timestamp_s'] = time_delta

    def convert(self, strings):
        col_to_char = self.col_to_char

        def match(x):
            if x in col_to_char:
                return col_to_char[x]
            close = difflib.get_close_matches(x, col_to_char, cutoff=.6)
            return col_to_char[close[0]]

        return ''.join(match(x) for x in strings if x)
