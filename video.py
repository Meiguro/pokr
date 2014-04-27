import gzip
import os
import struct
import time

import cv2
import numpy

import ocr
import struct

from cffi import FFI

DATA_DIR = os.path.abspath(os.path.dirname(__file__))

ffi = FFI()
ffi.cdef(open(DATA_DIR + '/accel.h').read())
C = ffi.dlopen(os.path.abspath(os.path.dirname(__file__)) + '/accel.so')


class ScreenExtractor(object):
    def __init__(self, fname=None, debug=False):
        self.last = None
        self.n = 0

    def handle(self, data):
        self.n += 1
        data['screen'] = ocr.extract_screen(data['frame'])
        trunc = data['screen'] >> 6  # / 64 -> values in [0, 3]
        data['changed'] = not numpy.array_equal(trunc, self.last)
        data['frame_n'] = self.n
        if not data['changed']:
            raise StopIteration

        self.last = trunc


class OCREngine(object):
    def __init__(self, sprites, sprite_text, sprite_width, sprite_height, color_map):
        self.sprite_width = sprite_width
        self.sprite_height = sprite_height
        self.color_map = color_map

        def pack_image(buf):
            out = []
            height = self.sprite_height
            for n in range(0, len(buf) / height):
                column = 0
                for color in buf[n*height:n*height+height]:
                    column = (column << 2) | color
                out.append(column)
            return out

        def pack_to_struct(buf):
            # for binary search to work properly, we need to have
            # sprites arranged lexicographically by image bytes.
            # this lets us sort them properly
            buf = pack_image(buf)
            return struct.pack('%dI' % len(buf), *buf)

        self.sprite_text = ''
        self.sprites = ffi.new('struct sprite[]', len(sprites) + 1)
        self.n_sprites = len(sprites)
        sprites.sort(key=lambda (id, buf): pack_to_struct(buf))
        for sprite_n, (sprite_id, sprite_buf) in enumerate(sprites):
            sprite = self.sprites[sprite_n]
            sprite.id = sprite_id
            text = sprite_text.get(sprite_id, '#')
            sprite.text = text.encode('utf-8')
            sprite.image = pack_image(sprite_buf)
            sprite.width = max(3, len(sprite_buf) / sprite_height)
        self.sprites[len(sprites)].id = -1
        #print repr(list(self.sprites[0].image[0:128]))

        self.map = ffi.new('uint8_t[]', 256)
        #  61 is the dark red of the down arrow on text boxes
        #  Map it to 2 so the OCR engine's 3 color heuristic isn't confused.
        for color, n in self.color_map:
            for off in range(-9, 9):
                self.map[color + off] = n

        self.last_image = None
        self.last_matched = None

    def identify(self, screen):
        ''' recognize text on screen, return list of lists of
        [ypos, xbegin, xend, text]
        '''
        max_matches = 128
        image = screen.flatten(order='F')
        pimage = ffi.cast('uint8_t *', image.ctypes.data)
        C.translate_bytes(pimage, 240*160, self.map)
        if numpy.array_equal(image, self.last_image):
            return self.last_out
        self.last_image = image
        results = ffi.new('struct sprite_match[]', max_matches)
        matched = C.identify_sprites(pimage, self.sprites, self.n_sprites, self.sprite_width, self.sprite_height, results, max_matches)
        if self.last_matched is not None:
            overlap = ffi.new('int *')
            merged = ffi.new('struct sprite_match[]', max_matches)
            merge_match = C.merge_sprites(self.last_matched, max_matches, results, max_matches, merged, max_matches, overlap)
            #for n in xrange(overlap):
            #s    print (merged[n].text and ffi.string(merged[n].text)),
            #print 'matched', overlap
            if overlap[0] > 3:
                results = merged
                matched = merge_match
        self.last_matched = results
        out = []
        lastY = None
        for n in xrange(matched):
            match = results[n]
            if match.y != lastY:
                out += [[match.y, match.x, match.x, '']]
                lastY = match.y
            out[-1][-1] += ' ' * match.space + ffi.string(match.sp.text)
            out[-1][2] = match.x
        self.last_out = out
        return out


class ScreenCompressor(object):
    '''
    Experimental compression for very low-bandwidth video streaming.

    Packing each frame as 2bpp as a series of 8x8 blocks (matching the GameBoy
    sprite size), then applying a generic LZ77 compressor (LZ4 performs better
    than DEFLATE) reduces the video stream from >1000kbps to <10kbps (<5MB/hr).
    '''

    FRAME_BYTES = 144 * 160 * 2 / 8

    def __init__(self, fname=None, debug=False):
        self.last = None
        self.fd = None
        if fname:
            self.fd = gzip.GzipFile(time.strftime(fname), "w")
        self.debug = debug
        self.start = time.time()

    def handle(self, data):
        trunc = data['screen'] >> 6  # / 64
        trunc_flat = trunc.flatten()
        ptrunc = ffi.cast("uint8_t *", trunc_flat.ctypes.data)
        pout = ffi.new('uint8_t[]', self.FRAME_BYTES)
        C.pack2bpp(ptrunc, pout)

        if self.fd:
            self.fd.write('+f\xc9q')
            self.fd.write(struct.pack('<LB', data.get('timestamp_s', 0), data['frame_n'] & 0xff))
            self.fd.write(ffi.buffer(pout))
        self.last = trunc

        if self.debug:
            n = data['frame_n']
            if n&0xf==0:
                print '%.3f %.3f' % (n/60., (n/60.) / (time.time() - self.start))
            self.unpack(pout, trunc)
            cv2.imshow('Stream', cv2.resize(trunc * 80, (160 * 4, 144 * 4), interpolation=cv2.INTER_NEAREST))
            cv2.waitKey(1)

    def unpack(self, pout, frame):
        off = 0
        for py in range(18):
            for px in range(20):
                for n in range(8):
                    a = pout[off] | (pout[off + 1] << 8)
                    off += 2
                    for nx in range(8):
                        frame[py*8+n][px*8+nx] = a & 3
                        a >>= 2

if __name__ == '__main__':
    import timestamp

    class SavedStreamProcessor(ocr.StreamProcessor):
        def get_stream_location(self):
            import sys
            if len(sys.argv) > 1:
                return sys.argv[1]
            else:
                return '/home/ryan/games/tpp/stream.flv'

    proc = SavedStreamProcessor(default_handlers=False)
    proc.add_handler(ScreenExtractor().handle)
    proc.add_handler(timestamp.TimestampRecognizer().handle)
    proc.add_handler(ScreenCompressor(debug=True, fname='frames.raw.gz').handle)
    proc.run()
    while True:
        time.sleep(1)  # loop until killed with ctrl-c
