import argparse
import os
import time

import requests
from pydub import AudioSegment
from pydub.effects import speedup


class WordAudioGenerator:
    """
    单词音频生成器类
    使用有道词典API下载单词发音，并生成可定制的跟读音频。
    增加了重试机制和错误处理。
    """

    def __init__(self, accent=1, max_retries=3, retry_delay=1):
        """
        初始化
        :param accent: 发音类型。0为美音，1为英音。
        :param max_retries: 最大重试次数
        :param retry_delay: 重试延迟（秒）
        """
        self.accent = accent
        self.accent_dir = 'Speech_EN' if accent == 1 else 'Speech_US'
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._ensure_dir_exists(self.accent_dir)

    @staticmethod
    def _ensure_dir_exists(dir_name):
        """确保存储音频的目录存在，不存在则创建"""
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
            print(f"创建目录: {dir_name}")

    def _is_valid_audio_file(self, file_path):
        """检查音频文件是否有效"""
        try:
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                return False

            # 尝试打开文件，验证是否为有效音频
            with open(file_path, 'rb') as f:
                header = f.read(4)
                # 检查是否是有效的MP3文件
                if header.startswith(b'ID3') or header.startswith(b'\xFF\xFB') or header.startswith(b'\xFF\xF3'):
                    return True
            return False
        except:
            return False

    def _download_word_audio_with_retry(self, word, retry_count=0):
        """
        带重试机制的单词音频下载
        """
        word = word.lower().strip()
        if not word:
            return None

        file_path = os.path.join(self.accent_dir, f"{word}.mp3")

        # 如果文件已存在且有效，则直接返回
        if os.path.exists(file_path) and self._is_valid_audio_file(file_path):
            print(f"音频已存在且有效，跳过: {word}")
            return file_path

        # 如果文件存在但无效，删除它
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"删除无效音频文件: {word}")
            except:
                pass

        # 构造有道API请求URL
        url = f"http://dict.youdao.com/dictvoice?type={self.accent}&audio={word}"

        try:
            print(f"正在下载: {word}")

            # 使用requests库下载，支持更好的重试和错误处理
            response = requests.get(url, stream=True, timeout=10)
            response.raise_for_status()

            # 保存文件
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # 验证下载的文件
            if not self._is_valid_audio_file(file_path):
                raise ValueError("下载的文件无效")

            print(f"下载成功: {word}")
            time.sleep(0.3)  # 增加延迟，避免请求过快
            return file_path

        except Exception as e:
            print(f"下载失败 [{word}]: {e}")

            # 删除可能损坏的文件
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass

            # 重试逻辑
            if retry_count < self.max_retries:
                print(f"重试 {retry_count + 1}/{self.max_retries} 下载: {word}")
                time.sleep(self.retry_delay)
                return self._download_word_audio_with_retry(word, retry_count + 1)
            else:
                print(f"达到最大重试次数，放弃下载: {word}")
                return None

    def _download_word_audio(self, word):
        """包装下载函数，使用重试机制"""
        return self._download_word_audio_with_retry(word, 0)

    @staticmethod
    def _create_silence(duration_ms):
        """生成指定时长的静音片段，用于间隔"""
        return AudioSegment.silent(duration=duration_ms)

    def _load_audio_with_retry(self, mp3_path, word, retry_count=0):
        """
        带重试机制的音频加载
        """
        try:
            # 尝试加载音频
            audio = AudioSegment.from_mp3(mp3_path)

            # 验证音频长度和属性
            if len(audio) == 0:
                raise ValueError("音频长度为0")

            return audio

        except Exception as e:
            print(f"加载音频失败 [{word}]: {e}")

            # 如果文件存在但加载失败，尝试重新下载
            if retry_count < self.max_retries:
                print(f"重试 {retry_count + 1}/{self.max_retries} 加载: {word}")

                # 删除可能损坏的文件
                if os.path.exists(mp3_path):
                    try:
                        os.remove(mp3_path)
                    except:
                        pass

                # 重新下载
                time.sleep(self.retry_delay)
                new_mp3_path = self._download_word_audio_with_retry(word, 0)

                if new_mp3_path and os.path.exists(new_mp3_path):
                    return self._load_audio_with_retry(new_mp3_path, word, retry_count + 1)
                else:
                    return None
            else:
                print(f"达到最大重试次数，放弃加载: {word}")
                return None

    def generate_audio(self, word_list, repeat_times=2, interval_ms=1000, playback_speed=1.0,
                       output_file="word_review.mp3"):
        """
        生成最终的跟读音频文件
        :param word_list: 单词列表
        :param repeat_times: 每个单词重复的次数
        :param interval_ms: 重复之间的间隔（毫秒）
        :param playback_speed: 播放速度。1.0为原速，大于1.0加快，小于1.0减慢。
        :param output_file: 输出文件名
        """
        print("开始生成音频...")
        final_audio = AudioSegment.empty()
        silence = self._create_silence(interval_ms)

        successful_words = []
        failed_words = []

        for i, word in enumerate(word_list, 1):
            print(f"处理单词 ({i}/{len(word_list)}): {word}")

            mp3_path = self._download_word_audio(word)
            if not mp3_path:
                print(f"无法获取单词发音: {word}")
                failed_words.append(word)
                continue

            # 使用重试机制加载音频
            word_audio = self._load_audio_with_retry(mp3_path, word)

            if not word_audio:
                print(f"跳过单词（加载音频失败）: {word}")
                failed_words.append(word)
                continue

            try:
                # 根据设定的重复次数拼接当前单词的音频
                for _ in range(repeat_times):
                    final_audio += word_audio
                    final_audio += silence  # 添加间隔
                # 一个单词结束后，可以添加一个稍长的间隔
                final_audio += self._create_silence(500)

                successful_words.append(word)

            except Exception as e:
                print(f"处理音频失败 [{word}]: {e}")
                failed_words.append(word)

        if len(successful_words) == 0:
            print("没有成功处理任何单词，无法生成音频文件。")
            return

        # 调整语速
        if playback_speed != 1.0 and len(final_audio) > 0:
            try:
                print(f"调整语速: {playback_speed}")
                final_audio = speedup(final_audio, playback_speed=playback_speed, chunk_size=150, crossfade=25)
            except Exception as e:
                print(f"语速调整失败，将导出原速音频: {e}")

        # 导出最终文件
        try:
            print(f"正在导出音频文件: {output_file}")
            final_audio.export(output_file, format="mp3", bitrate="192k")
            print(f"✅ 跟读音频已生成: {output_file}")
            print(f"✅ 成功处理 {len(successful_words)} 个单词")

            if failed_words:
                print(f"❌ 失败的单词 ({len(failed_words)} 个): {', '.join(failed_words)}")

        except Exception as e:
            print(f"导出音频文件失败: {e}")

            # 尝试使用不同的格式
            try:
                print("尝试使用WAV格式导出...")
                wav_output = output_file.replace('.mp3', '.wav')
                final_audio.export(wav_output, format="wav")
                print(f"✅ 跟读音频已生成 (WAV格式): {wav_output}")
            except Exception as e2:
                print(f"WAV格式导出也失败: {e2}")


def main():
    word_list = [
        "happen", "since", "break", "building", "wish", "festival", "language", "example", "healthy", "share",
        "taste", "company", "sound", "museum", "difficult", "close", "light", "stand", "late", "excite",
        "tomorrow", "mind", "forget", "anything", "order", "scientist", "heart", "fall", "collect", "history",
        "weather", "afraid", "protect", "catch", "seem", "chance", "improve", "culture", "wear", "return",
        "realize", "science", "develop", "village", "environment", "allow", "possible", "pick", "report",
        "note", "able", "news", "angry", "mainly", "arrive", "strong", "suddenly", "quite", "hurt", "head",
        "business", "invite", "laugh", "store", "encourage", "favorite", "plane", "ticket", "throw", "traffic",
        "join", "provide", "trouble", "meeting", "whole", "paint", "mobile", "newspaper", "library", "several",
        "middle", "agree", "dangerous", "mistake", "include", "create", "carefully", "spring", "carry",
        "smell"
    ]

    if not word_list:
        print("单词列表为空。")
        return

    # 使用测试列表运行
    generator = WordAudioGenerator(accent=1, max_retries=3, retry_delay=1)
    generator.generate_audio(
        word_list=word_list,
        repeat_times=2,
        interval_ms=1000,
        playback_speed=1.0,
        output_file="word_review_20251228.mp3"
    )


if __name__ == "__main__":
    main()
