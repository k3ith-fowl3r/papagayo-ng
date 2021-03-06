# Papagayo-NG, a lip-sync tool for use with several different animation suites
# Original Copyright (C) 2005 Mike Clifton
# Contact information at http://www.lostmarble.com
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import math
import shutil
import codecs
import importlib

from Rhubarb import Rhubarb, RhubarbTimeoutException

try:
    import configparser
except ImportError:
    import ConfigParser as configparser

import PySide2.QtCore as QtCore

from utilities import *
from PronunciationDialogQT import PronunciationDialog

if sys.platform != "darwin":
    import SoundPlayerQT as SoundPlayer
else:
    import SoundPlayerOSX as SoundPlayer


strip_symbols = '.,!?;-/()"'
strip_symbols += '\N{INVERTED QUESTION MARK}'


###############################################################

class LipsyncPhoneme:
    def __init__(self, text="", frame=0):
        self.text = text
        self._orig_frame = frame
        self._frame = frame
        self.dirty = False
        self.is_phoneme = True

        @property
        def frame(self):
            return self._frame

        @frame.setter
        def frame(self, value):
            if self._frame != value:
                self.dirty = True
                self._frame = value
            if self._frame == self._orig_frame:
                self.dirty = False


###############################################################

class LipsyncWord:
    def __init__(self):
        self.text = ""
        self.start_frame = 0
        self.end_frame = 0
        self.phonemes = []
        self.is_phoneme = False

    def run_breakdown(self, parent_window, language, languagemanager, phonemeset):
        self.phonemes = []
        try:
            text = self.text.strip(strip_symbols)
            details = languagemanager.language_table[language]
            if details["type"] == "breakdown":
                breakdown = importlib.import_module(details["breakdown_class"])
                pronunciation_raw = breakdown.breakdownWord(text)
            elif details["type"] == "dictionary":
                if languagemanager.current_language != language:
                    languagemanager.load_language(details)
                    languagemanager.current_language = language
                if details["case"] == "upper":
                    pronunciation_raw = languagemanager.raw_dictionary[text.upper()]
                elif details["case"] == "lower":
                    pronunciation_raw = languagemanager.raw_dictionary[text.lower()]
                else:
                    pronunciation_raw = languagemanager.raw_dictionary[text]
            else:
                pronunciation_raw = phonemeDictionary[text.upper()]

            pronunciation = []
            for i in range(len(pronunciation_raw)):
                try:
                    pronunciation.append(phonemeset.conversion[pronunciation_raw[i]])
                except KeyError:
                    print(("Unknown phoneme:", pronunciation_raw[i], "in word:", text))

            for p in pronunciation:
                if len(p) == 0:
                    continue
                phoneme = LipsyncPhoneme()
                phoneme.text = p
                self.phonemes.append(phoneme)
        except KeyError:
            # this word was not found in the phoneme dictionary
            # TODO: This now depends on QT, make it neutral!
            dlg = PronunciationDialog(parent_window, phonemeset.set)
            dlg.word_label.setText("{} {}".format(dlg.word_label.text(), self.text))
            dlg.exec_()
            if dlg.gave_ok:
                for p in dlg.phoneme_ctrl.text().split():
                    if len(p) == 0:
                        continue
                    phoneme = LipsyncPhoneme()
                    phoneme.text = p
                    self.phonemes.append(phoneme)
            dlg.destroy()

    def reposition_phoneme(self, phoneme):
        current_id = 0
        for i in range(len(self.phonemes)):
            if phoneme is self.phonemes[i]:
                current_id = i
        if (current_id > 0) and (phoneme.frame < self.phonemes[current_id - 1].frame + 1):
            phoneme.frame = self.phonemes[current_id - 1].frame + 1
        if (current_id < len(self.phonemes) - 1) and (phoneme.frame > self.phonemes[current_id + 1].frame - 1):
            phoneme.frame = self.phonemes[current_id + 1].frame - 1
        if phoneme.frame < self.start_frame:
            phoneme.frame = self.start_frame
        if phoneme.frame > self.end_frame:
            phoneme.frame = self.end_frame


###############################################################

class LipsyncPhrase:
    def __init__(self):
        self.text = ""
        self.start_frame = 0
        self.end_frame = 0
        self.words = []
        self.is_phoneme = False

    def run_breakdown(self, parent_window, language, languagemanager, phonemeset):
        self.words = []
        for w in self.text.split():
            if len(w) == 0:
                continue
            word = LipsyncWord()
            word.text = w
            self.words.append(word)
        for word in self.words:
            word.run_breakdown(parent_window, language, languagemanager, phonemeset)

    def reposition_word(self, word):
        current_id = 0
        for i in range(len(self.words)):
            if word is self.words[i]:
                current_id = i
        if (current_id > 0) and (word.start_frame < self.words[current_id - 1].end_frame + 1):
            word.start_frame = self.words[current_id - 1].end_frame + 1
            if word.end_frame < word.start_frame + 1:
                word.end_frame = word.start_frame + 1
        if (current_id < len(self.words) - 1) and (word.end_frame > self.words[current_id + 1].start_frame - 1):
            word.end_frame = self.words[current_id + 1].start_frame - 1
            if word.start_frame > word.end_frame - 1:
                word.start_frame = word.end_frame - 1
        if word.start_frame < self.start_frame:
            word.start_frame = self.start_frame
        if word.end_frame > self.end_frame:
            word.end_frame = self.end_frame
        if word.end_frame < word.start_frame:
            word.end_frame = word.start_frame
        frame_duration = word.end_frame - word.start_frame + 1
        phoneme_count = len(word.phonemes)
        # now divide up the total time by phonemes
        if frame_duration > 0 and phoneme_count > 0:
            frames_per_phoneme = float(frame_duration) / float(phoneme_count)
            if frames_per_phoneme < 1:
                frames_per_phoneme = 1
        else:
            frames_per_phoneme = 1
        # finally, assign frames based on phoneme durations
        cur_frame = word.start_frame
        for phoneme in word.phonemes:
            phoneme.frame = int(round(cur_frame))
            cur_frame += frames_per_phoneme
        for phoneme in word.phonemes:
            word.reposition_phoneme(phoneme)


###############################################################

class LipsyncVoice:
    def __init__(self, name="Voice"):
        self.name = name
        self.text = ""
        self.phrases = []
        self.num_children = 0

    def run_breakdown(self, frame_duration, parent_window, language, languagemanager, phonemeset):
        # make sure there is a space after all punctuation marks
        repeat_loop = True
        while repeat_loop:
            repeat_loop = False
            for i in range(len(self.text) - 1):
                if (self.text[i] in ".,!?;-/()") and (not self.text[i + 1].isspace()):
                    self.text = "{} {}".format(self.text[:i + 1], self.text[i + 1:])
                    repeat_loop = True
                    break
        # break text into phrases
        self.phrases = []
        for line in self.text.splitlines():
            if len(line) == 0:
                continue
            phrase = LipsyncPhrase()
            phrase.text = line
            self.phrases.append(phrase)
        # now break down the phrases
        for phrase in self.phrases:
            phrase.run_breakdown(parent_window, language, languagemanager, phonemeset)
        # for first-guess frame alignment, count how many phonemes we have
        phoneme_count = 0
        for phrase in self.phrases:
            for word in phrase.words:
                if len(word.phonemes) == 0:  # deal with unknown words
                    phoneme_count += 4
                for phoneme in word.phonemes:
                    phoneme_count += 1
        # now divide up the total time by phonemes
        if frame_duration > 0 and phoneme_count > 0:
            frames_per_phoneme = int(float(frame_duration) / float(phoneme_count))
            if frames_per_phoneme < 1:
                frames_per_phoneme = 1
        else:
            frames_per_phoneme = 1
        # finally, assign frames based on phoneme durations
        cur_frame = 0
        for phrase in self.phrases:
            for word in phrase.words:
                for phoneme in word.phonemes:
                    phoneme.frame = cur_frame
                    cur_frame += frames_per_phoneme
                if len(word.phonemes) == 0:  # deal with unknown words
                    word.start_frame = cur_frame
                    word.end_frame = cur_frame + 3
                    cur_frame += 4
                else:
                    word.start_frame = word.phonemes[0].frame
                    word.end_frame = word.phonemes[-1].frame + frames_per_phoneme - 1
            phrase.start_frame = phrase.words[0].start_frame
            phrase.end_frame = phrase.words[-1].end_frame

    def reposition_phrase(self, phrase, last_frame):
        current_id = 0
        for i in range(len(self.phrases)):
            if phrase is self.phrases[i]:
                current_id = i
        if (current_id > 0) and (phrase.start_frame < self.phrases[current_id - 1].end_frame + 1):
            phrase.start_frame = self.phrases[current_id - 1].end_frame + 1
            if phrase.end_frame < phrase.start_frame + 1:
                phrase.end_frame = phrase.start_frame + 1
        if (current_id < len(self.phrases) - 1) and (phrase.end_frame > self.phrases[current_id + 1].start_frame - 1):
            phrase.end_frame = self.phrases[current_id + 1].start_frame - 1
            if phrase.start_frame > phrase.end_frame - 1:
                phrase.start_frame = phrase.end_frame - 1
        if phrase.start_frame < 0:
            phrase.start_frame = 0
        if phrase.end_frame > last_frame:
            phrase.end_frame = last_frame
        if phrase.start_frame > phrase.end_frame - 1:
            phrase.start_frame = phrase.end_frame - 1
        # for first-guess frame alignment, count how many phonemes we have
        frame_duration = phrase.end_frame - phrase.start_frame + 1
        phoneme_count = 0
        for word in phrase.words:
            if len(word.phonemes) == 0:  # deal with unknown words
                phoneme_count += 4
            for phoneme in word.phonemes:
                phoneme_count += 1
        # now divide up the total time by phonemes
        if frame_duration > 0 and phoneme_count > 0:
            frames_per_phoneme = float(frame_duration) / float(phoneme_count)
            if frames_per_phoneme < 1:
                frames_per_phoneme = 1
        else:
            frames_per_phoneme = 1
        # finally, assign frames based on phoneme durations
        cur_frame = phrase.start_frame
        for word in phrase.words:
            for phoneme in word.phonemes:
                phoneme.frame = int(round(cur_frame))
                cur_frame += frames_per_phoneme
            if len(word.phonemes) == 0:  # deal with unknown words
                word.start_frame = cur_frame
                word.end_frame = cur_frame + 3
                cur_frame += 4
            else:
                word.start_frame = word.phonemes[0].frame
                word.end_frame = word.phonemes[-1].frame + int(round(frames_per_phoneme)) - 1
            phrase.reposition_word(word)

    def open(self, in_file):
        self.name = in_file.readline().strip()
        temp_text = in_file.readline().strip()
        self.text = temp_text.replace('|', '\n')
        num_phrases = int(in_file.readline())
        for p in range(num_phrases):
            self.num_children += 1
            phrase = LipsyncPhrase()
            phrase.text = in_file.readline().strip()
            phrase.start_frame = int(in_file.readline())
            phrase.end_frame = int(in_file.readline())
            num_words = int(in_file.readline())
            for w in range(num_words):
                self.num_children += 1
                word = LipsyncWord()
                word_line = in_file.readline().split()
                word.text = word_line[0]
                word.start_frame = int(word_line[1])
                word.end_frame = int(word_line[2])
                num_phonemes = int(word_line[3])
                for p2 in range(num_phonemes):
                    self.num_children += 1
                    phoneme = LipsyncPhoneme()
                    phoneme_line = in_file.readline().split()
                    phoneme.frame = int(phoneme_line[0])
                    phoneme.text = phoneme_line[1]
                    word.phonemes.append(phoneme)
                phrase.words.append(word)
            self.phrases.append(phrase)

    def save(self, out_file):
        out_file.write("\t{}\n".format(self.name))
        temp_text = self.text.replace('\n', '|')
        out_file.write("\t{}\n".format(temp_text))
        out_file.write("\t{:d}\n".format(len(self.phrases)))
        for phrase in self.phrases:
            out_file.write("\t\t{}\n".format(phrase.text))
            out_file.write("\t\t{:d}\n".format(phrase.start_frame))
            out_file.write("\t\t{:d}\n".format(phrase.end_frame))
            out_file.write("\t\t{:d}\n".format(len(phrase.words)))
            for word in phrase.words:
                out_file.write(
                    "\t\t\t{} {:d} {:d} {:d}\n".format(word.text, word.start_frame, word.end_frame, len(word.phonemes)))
                for phoneme in word.phonemes:
                    out_file.write("\t\t\t\t{:d} {}\n".format(phoneme.frame, phoneme.text))

    def get_phoneme_at_frame(self, frame):
        for phrase in self.phrases:
            if (frame <= phrase.end_frame) and (frame >= phrase.start_frame):
                # we found the phrase that contains this frame
                word = None
                for w in phrase.words:
                    if (frame <= w.end_frame) and (frame >= w.start_frame):
                        word = w  # the frame is inside this word
                        break
                if word is not None:
                    # we found the word that contains this frame
                    for i in range(len(word.phonemes) - 1, -1, -1):
                        if frame >= word.phonemes[i].frame:
                            return word.phonemes[i].text
                break
        return "rest"

    def export(self, path):

        out_file = open(path, 'w')
        out_file.write("MohoSwitch1\n")
        phoneme = ""
        if len(self.phrases) > 0:
            start_frame = self.phrases[0].start_frame
            end_frame = self.phrases[-1].end_frame
            if start_frame != 0:
                phoneme = "rest"
                out_file.write("{:d} {}\n".format(1, phoneme))
        else:
            start_frame = 0
            end_frame = 1

        for frame in range(start_frame, end_frame + 1):
            next_phoneme = self.get_phoneme_at_frame(frame)
            if next_phoneme != phoneme:
                if phoneme == "rest":
                    # export an extra "rest" phoneme at the end of a pause between words or phrases
                    out_file.write("{:d} {}\n".format(frame, phoneme))
                phoneme = next_phoneme
                out_file.write("{:d} {}\n".format(frame + 1, phoneme))
        out_file.write("{:d} {}\n".format(end_frame + 2, "rest"))
        out_file.close()

    def export_images(self, path, currentmouth):
        try:
            self.config
        except AttributeError:
            self.config = QtCore.QSettings("Lost Marble", "Papagayo-NG")
        phoneme = ""
        if len(self.phrases) > 0:
            start_frame = self.phrases[0].start_frame
            end_frame = self.phrases[-1].end_frame
        else:
            start_frame = 0
            end_frame = 1
        if not self.config.value("MouthDir"):
            print("Use normal procedure.\n")
            phonemedict = {}
            for files in os.listdir(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "rsrc/mouths/") + currentmouth):
                phonemedict[os.path.splitext(files)[0]] = os.path.splitext(files)[1]
            for frame in range(start_frame, end_frame + 1):
                phoneme = self.get_phoneme_at_frame(frame)
                try:
                    shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rsrc/mouths/") +
                                currentmouth + "/" + phoneme + phonemedict[phoneme],
                                path + str(frame).rjust(6, '0') + phoneme + phonemedict[phoneme])
                except KeyError:
                    print("Phoneme \'{0}\' does not exist in chosen directory.".format(phoneme))

        else:
            print("Use this dir: {}\n".format(self.config.value("MouthDir")))
            phonemedict = {}
            for files in os.listdir(self.config.value("MouthDir")):
                phonemedict[os.path.splitext(files)[0]] = os.path.splitext(files)[1]
            for frame in range(start_frame, end_frame + 1):
                phoneme = self.get_phoneme_at_frame(frame)
                try:
                    shutil.copy("{}/{}{}".format(self.config.value("MouthDir"), phoneme, phonemedict[phoneme]),
                                "{}{}{}{}".format(path, str(frame).rjust(6, "0"), phoneme, phonemedict[phoneme]))
                except KeyError:
                    print("Phoneme \'{0}\' does not exist in chosen directory.".format(phoneme))

    def export_alelo(self, path, language, languagemanager):
        out_file = open(path, 'w')
        for phrase in self.phrases:
            for word in phrase.words:
                text = word.text.strip(strip_symbols)
                details = languagemanager.language_table[language]
                if languagemanager.current_language != language:
                    languagemanager.LoadLanguage(details)
                    languagemanager.current_language = language
                if details["case"] == "upper":
                    pronunciation = languagemanager.raw_dictionary[text.upper()]
                elif details["case"] == "lower":
                    pronunciation = languagemanager.raw_dictionary[text.lower()]
                else:
                    pronunciation = languagemanager.raw_dictionary[text]
                first = True
                position = -1
                #               print word.text
                for phoneme in word.phonemes:
                    #                   print phoneme.text
                    if first:
                        first = False
                    else:
                        try:
                            out_file.write("{:d} {:d} {}\n".format(last_phoneme.frame, phoneme.frame - 1,
                                                                   languagemanager.export_conversion[last_phoneme_text]))
                        except KeyError:
                            pass
                    if phoneme.text.lower() == "sil":
                        position += 1
                        out_file.write("{:d} {:d} sil\n".format(phoneme.frame, phoneme.frame))
                        continue
                    position += 1
                    last_phoneme_text = pronunciation[position]
                    last_phoneme = phoneme
                try:
                    out_file.write("{:d} {:d} {}\n".format(last_phoneme.frame, word.end_frame,
                                                           languagemanager.export_conversion[last_phoneme_text]))
                except KeyError:
                    pass
        out_file.close()


###############################################################

class LipsyncDoc:
    def __init__(self, langman, parent):
        self.dirty = False
        self.name = "Untitled"
        self.path = None
        self.fps = 24
        self.soundDuration = 72
        self.soundPath = ""
        self.sound = None
        self.voices = []
        self.current_voice = None
        self.language_manager = langman
        self.parent = parent

    def __del__(self):
        # Properly close down the sound object
        if self.sound is not None:
            del self.sound

    def open(self, path):
        self.dirty = False
        self.path = os.path.normpath(path)
        self.name = os.path.basename(path)
        self.sound = None
        self.voices = []
        self.current_voice = None
        in_file = open(self.path, 'r')
        in_file.readline()  # discard the header
        self.soundPath = in_file.readline().strip()
        if not os.path.isabs(self.soundPath):
            self.soundPath = os.path.normpath("{}/{}".format(os.path.dirname(self.path), self.soundPath))
        self.fps = int(in_file.readline())
        print(("self.path: {}".format(self.path)))
        self.soundDuration = int(in_file.readline())
        print(("self.soundDuration: {:d}".format(self.soundDuration)))
        num_voices = int(in_file.readline())
        for i in range(num_voices):
            voice = LipsyncVoice()
            voice.open(in_file)
            self.voices.append(voice)
        in_file.close()
        self.open_audio(self.soundPath)
        if len(self.voices) > 0:
            self.current_voice = self.voices[0]

    def open_audio(self, path):
        if self.sound is not None:
            del self.sound
            self.sound = None
        # self.soundPath = str(path.encode("utf-8"))
        self.soundPath = path  # .encode('latin-1', 'replace')
        self.sound = SoundPlayer.SoundPlayer(self.soundPath, self.parent)
        if self.sound.IsValid():
            print("valid sound")
            self.soundDuration = int(self.sound.Duration() * self.fps)
            print(("self.sound.Duration(): {:d}".format(int(self.sound.Duration()))))
            print(("frameRate: {:d}".format(int(self.fps))))
            print(("soundDuration1: {:d}".format(self.soundDuration)))
            if self.soundDuration < self.sound.Duration() * self.fps:
                self.soundDuration += 1
                print(("soundDuration2: {:d}".format(self.soundDuration)))
        else:
            self.sound = None

    def save(self, path):
        self.path = os.path.normpath(path)
        self.name = os.path.basename(path)
        if os.path.dirname(self.path) == os.path.dirname(self.soundPath):
            saved_sound_path = os.path.basename(self.soundPath)
        else:
            saved_sound_path = self.soundPath
        out_file = open(self.path, "w")
        out_file.write("lipsync version 1\n")
        out_file.write("{}\n".format(saved_sound_path))
        out_file.write("{:d}\n".format(self.fps))
        out_file.write("{:d}\n".format(self.soundDuration))
        out_file.write("{:d}\n".format(len(self.voices)))
        for voice in self.voices:
            voice.save(out_file)
        out_file.close()
        self.dirty = False

    def auto_recognize_phoneme(self):
        try:
            phonemes = Rhubarb(self.soundPath).run()
            if not phonemes:
                return
            end_frame = math.floor(self.fps * phonemes[-1]['end'])
            phrase = LipsyncPhrase()
            phrase.text = 'Auto detection rhubarb'
            phrase.start_frame = 0
            phrase.end_frame = end_frame

            word = LipsyncWord()
            word.text = 'rhubarb'
            word.start_frame = 0
            word.end_frame = end_frame

            for phoneme in phonemes:
                pg_phoneme = LipsyncPhoneme()
                pg_phoneme.frame = math.floor(self.fps * phoneme['start'])
                pg_phoneme.text = phoneme['value'] if phoneme['value'] != 'X' else 'rest'
                word.phonemes.append(pg_phoneme)

            phrase.words.append(word)
            self.current_voice.phrases.append(phrase)

        except RhubarbTimeoutException:
            pass


from phonemes import *


class PhonemeSet:
    __shared_state = {}

    def __init__(self):
        self.__dict__ = self.__shared_state
        self.set = []
        self.conversion = {}
        self.alternatives = phoneme_sets
        self.load(self.alternatives[0])

    def load(self, name=''):
        if name in self.alternatives:
            print("import phonemes_{} as phonemeset".format(name))
            phonemeset = importlib.import_module("phonemes_{}".format(name))
            # exec("import phonemes_%s as phonemeset" % name)
            # import phonemes_preston_blair as phonemeset
            self.set = phonemeset.phoneme_set
            self.conversion = phonemeset.phoneme_conversion
        else:
            print(("Can't find phonemeset! ({})".format(name)))
            return


class LanguageManager:
    __shared_state = {}

    def __init__(self):
        self.__dict__ = self.__shared_state
        self.language_table = {}
        self.phoneme_dictionary = {}
        self.raw_dictionary = {}
        self.current_language = ""

        self.export_conversion = {}
        self.init_languages()

    def load_dictionary(self, path):
        try:
            in_file = open(path, 'r')
        except FileNotFoundError:
            print("Unable to open phoneme dictionary!:{}".format(path))
            return
        # process dictionary entries
        for line in in_file.readlines():
            if line[0] == '#':
                continue  # skip comments in the dictionary
            # strip out leading/trailing whitespace
            line.strip()
            line = line.rstrip('\r\n')

            # split into components
            entry = line.split()
            if len(entry) == 0:
                continue
            # check if this is a duplicate word (alternate transcriptions end with a number in parentheses) - if so, throw it out
            if entry[0].endswith(')'):
                continue
            # add this entry to the in-memory dictionary
            for i in range(len(entry)):
                if i == 0:
                    self.raw_dictionary[entry[0]] = []
                else:
                    rawentry = entry[i]
                    self.raw_dictionary[entry[0]].append(rawentry)
        in_file.close()
        in_file = None

    def load_language(self, language_config, force=False):
        if self.current_language == language_config["label"] and not force:
            return
        self.current_language = language_config["label"]

        if "dictionaries" in language_config:
            for dictionary in language_config["dictionaries"]:
                self.load_dictionary(os.path.join(get_main_dir(),
                                                  language_config["location"],
                                                  language_config["dictionaries"][dictionary]))

    def language_details(self, dirname, names):
        if "language.ini" in names:
            config = configparser.ConfigParser()
            config.read(os.path.join(dirname, "language.ini"))
            label = config.get("configuration", "label")
            ltype = config.get("configuration", "type")
            details = {"label": label, "type": ltype, "location": dirname}
            if ltype == "breakdown":
                details["breakdown_class"] = config.get("configuration", "breakdown_class")
                self.language_table[label] = details
            elif ltype == "dictionary":
                try:
                    details["case"] = config.get("configuration", "case")
                except:
                    details["case"] = "upper"
                details["dictionaries"] = {}

                if config.has_section('dictionaries'):
                    for key, value in config.items('dictionaries'):
                        details["dictionaries"][key] = value
                self.language_table[label] = details
            else:
                print("unknown type ignored language not added to table")

    def init_languages(self):
        if len(self.language_table) > 0:
            return
        for path, dirs, files in os.walk(os.path.join(get_main_dir(), "rsrc/languages")):
            if "language.ini" in files:
                self.language_details(path, files)
