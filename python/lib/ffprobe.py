#!/usr/bin/python
# Filename: ffprobe.py
"""
Based on Python wrapper for ffprobe command line tool. ffprobe must exist in the path.
Author: Simon Hargreaves

"""

version='0.5'

import subprocess
import re
import sys
import os
import platform

class FFProbe:
    """
    FFProbe wraps the ffprobe command and pulls the data into an object form::
        metadata=FFProbe('multimedia-file.mov')
    """
    def __init__(self,video_file):
        self.video_file=video_file
        try:
            with open(os.devnull, 'w') as tempf:
                subprocess.check_call(["ffprobe","-h"],stdout=tempf,stderr=tempf)
        except:
            raise IOError('ffprobe not found.')
        if os.path.isfile(video_file):
            video_file = self.video_file.replace(" ", "\ ")

            if str(platform.system())=='Windows':
                cmd=["ffprobe", "-show_streams", video_file]
            else:
                cmd=["ffprobe -show_streams " + video_file]

            p = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=True)
            self.format=None
            self.created=None
            self.duration=None
            self.start=None
            self.bitrate=None
            self.creation_time=None
            self.streams=[]
            self.video=[]
            self.audio=[]
            datalines=[]

            for a in iter(p.stdout.readline, b''):

                if re.match('\[STREAM\]',a):
                    datalines=[]
                elif re.match('\[\/STREAM\]',a):
                    self.streams.append(FFStream(datalines))
                    datalines=[]
                else:
                    datalines.append(a)
            for a in iter(p.stderr.readline, b''):
                if re.match('\[STREAM\]',a):
                    datalines=[]
                elif re.match('\[\/STREAM\]',a):
                    self.streams.append(FFStream(datalines))
                    datalines=[]
                else:
                    datalines.append(a)
            p.stdout.close()
            p.stderr.close()
            for a in self.streams:
                if a.isAudio():
                    self.audio.append(a)
                if a.isVideo():
                    self.video.append(a)
        else:
            raise IOError('No such media file ' + video_file)


class FFStream:
    """
    An object representation of an individual stream in a multimedia file.
    """
    def __init__(self,datalines):
        for a in datalines:
            if re.match(r'^.+=.+$', a) is None:
                print "Warning: detected incorrect stream metadata line format: %s" % a
            else:
                (key,val)=a.strip().split('=')
                key = key.lstrip("TAG:")
                self.__dict__[key]=val

    def isAudio(self):
        """
        Is this stream labelled as an audio stream?
        """
        val=False
        if self.__dict__['codec_type']:
            if str(self.__dict__['codec_type']) == 'audio':
                val=True
        return val

    def isVideo(self):
        """
        Is the stream labelled as a video stream.
        """
        val=False
        if self.__dict__['codec_type']:
            if self.codec_type == 'video':
                val=True
        return val

    def isSubtitle(self):
        """
        Is the stream labelled as a subtitle stream.
        """
        val=False
        if self.__dict__['codec_type']:
            if str(self.codec_type)=='subtitle':
                val=True
        return val

    def frameSize(self):
        """
        Returns the pixel frame size as an integer tuple (width,height) if the stream is a video stream.
        Returns None if it is not a video stream.
        """
        size=None
        if self.isVideo():
            if self.__dict__['width'] and self.__dict__['height']:
                try:
                    size=(int(self.__dict__['width']),int(self.__dict__['height']))
                except Exception as e:
                    print "None integer size %s:%s" %(str(self.__dict__['width']),str(+self.__dict__['height']))
                    size=(0,0)
        return size

    def pixelFormat(self):
        """
        Returns a string representing the pixel format of the video stream. e.g. yuv420p.
        Returns none is it is not a video stream.
        """
        f=None
        if self.isVideo():
            if self.__dict__['pix_fmt']:
                f=self.__dict__['pix_fmt']
        return f

    def frames(self):
        """
        Returns the length of a video stream in frames. Returns 0 if not a video stream.
        """
        f=0
        if self.isVideo() or self.isAudio():
            if self.__dict__['nb_frames']:
                try:
                    f=int(self.__dict__['nb_frames'])
                except Exception as e:
                    print "None integer frame count"
        return f

    def durationSeconds(self):
        """
        Returns the runtime duration of the video stream as a floating point number of seconds.
        Returns 0.0 if not a video stream.
        """
        f=0.0
        if self.isVideo() or self.isAudio():
            if self.__dict__['duration']:
                try:
                    f=float(self.__dict__['duration'])
                except Exception as e:
                    print "None numeric duration"
        return f

    def language(self):
        """
        Returns language tag of stream. e.g. eng
        """
        lang=None
        if self.__dict__['TAG:language']:
            lang=self.__dict__['TAG:language']
        return lang

    def codec(self):
        """
        Returns a string representation of the stream codec.
        """
        codec_name=None
        if self.__dict__['codec_name']:
            codec_name=self.__dict__['codec_name']
        return codec_name

    def codecDescription(self):
        """
        Returns a long representation of the stream codec.
        """
        codec_d=None
        if self.__dict__['codec_long_name']:
            codec_d=self.__dict__['codec_long_name']
        return codec_d

    def codecTag(self):
        """
        Returns a short representative tag of the stream codec.
        """
        codec_t=None
        if self.__dict__['codec_tag_string']:
            codec_t=self.__dict__['codec_tag_string']
        return codec_t

    def bitrate(self):
        """
        Returns bitrate as an integer in bps
        """
        b=0
        if self.__dict__['bit_rate']:
            try:
                b=int(self.__dict__['bit_rate'])
            except Exception as e:
                print "None integer bitrate"
        return b

if __name__ == '__main__':
    print "Module ffprobe"
