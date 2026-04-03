import os
import threading
import warnings
from queue import Queue

import pyttsx3
from pydub import AudioSegment
from pydub.effects import speedup

warnings.filterwarnings("ignore")


class LocalWordAudioGenerator:
    """
    本地单词音频生成器
    使用系统内置的TTS引擎，完全离线工作
    """

    def __init__(self, rate=150, volume=1.0, voice_type=None, voice_dir='Speech_EN'):
        """
        初始化本地TTS引擎

        :param rate: 语速 (默认150，范围50-300)
        :param volume: 音量 (默认1.0，范围0.0-1.0)
        :param voice_type: 语音类型，可选 'male'/'female'/None
        :param voice_dir: 音频保存目录
        """
        self.voice_dir = voice_dir
        self._ensure_dir_exists(self.voice_dir)

        # 初始化TTS引擎
        self.engine = self._init_tts_engine(rate, volume, voice_type)
        self.voice_id = None

        # 打印可用语音信息
        self._print_voice_info()

    def _init_tts_engine(self, rate, volume, voice_type):
        """初始化TTS引擎"""
        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', rate)
            engine.setProperty('volume', volume)

            # 获取可用语音
            voices = engine.getProperty('voices')

            # 选择语音类型
            if voice_type:
                voice_type = voice_type.lower()
                for voice in voices:
                    voice_name = voice.name.lower()
                    if voice_type == 'male' and 'male' in voice_name:
                        engine.setProperty('voice', voice.id)
                        self.voice_id = voice.id
                        break
                    elif voice_type == 'female' and 'female' in voice_name:
                        engine.setProperty('voice', voice.id)
                        self.voice_id = voice.id
                        break
                    elif 'david' in voice_name or 'zira' in voice_name:  # Windows默认英文语音
                        engine.setProperty('voice', voice.id)
                        self.voice_id = voice.id

            return engine

        except Exception as e:
            print(f"初始化TTS引擎失败: {e}")
            print("请确保已安装必要的语音引擎：")
            print("- Windows: 已内置语音引擎")
            print("- macOS: 需要安装: brew install pyttsx3")
            print("- Linux: 需要安装: sudo apt-get install espeak")
            return None

    def _print_voice_info(self):
        """打印语音信息"""
        if self.engine:
            voices = self.engine.getProperty('voices')
            print(f"可用的语音引擎 ({len(voices)} 个):")
            for i, voice in enumerate(voices):
                print(f"  {i + 1}. {voice.name} (ID: {voice.id[:50]}...)")

    @staticmethod
    def _ensure_dir_exists(dir_name):
        """确保存储音频的目录存在"""
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
            print(f"创建目录: {dir_name}")

    def _is_valid_audio_file(self, file_path):
        """检查音频文件是否有效"""
        try:
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                return False

            # 尝试加载音频文件
            audio = AudioSegment.from_file(file_path)
            return len(audio) > 100  # 音频长度至少100毫秒

        except Exception as e:
            return False

    def _save_word_audio_local(self, word):
        """
        使用本地TTS生成并保存单词音频

        :param word: 单词
        :return: 音频文件路径
        """
        if not self.engine:
            print("TTS引擎未初始化")
            return None

        word = word.lower().strip()
        if not word:
            return None

        file_path = os.path.join(self.voice_dir, f"{word}.mp3")

        # 如果文件已存在且有效，直接返回
        if os.path.exists(file_path) and self._is_valid_audio_file(file_path):
            print(f"音频已存在，跳过: {word}")
            return file_path

        # 删除可能损坏的文件
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass

        try:
            print(f"生成音频: {word}")

            # 保存临时文件
            temp_file = os.path.join(self.voice_dir, f"{word}_temp.wav")

            # 使用TTS生成音频
            self.engine.save_to_file(word, temp_file)
            self.engine.runAndWait()

            # 转换格式为mp3
            if os.path.exists(temp_file):
                audio = AudioSegment.from_wav(temp_file)
                audio.export(file_path, format="mp3", bitrate="192k")
                os.remove(temp_file)

                # 验证文件
                if self._is_valid_audio_file(file_path):
                    print(f"✅ 生成成功: {word}")
                    return file_path
                else:
                    print(f"❌ 生成的文件无效: {word}")
                    return None
            else:
                print(f"❌ 生成失败: {word}")
                return None

        except Exception as e:
            print(f"生成音频失败 [{word}]: {e}")
            return None

    def _generate_audio_parallel(self, word_list, num_threads=4):
        """
        多线程并行生成音频，加快处理速度

        :param word_list: 单词列表
        :param num_threads: 线程数
        """
        print(f"使用 {num_threads} 个线程并行生成音频...")

        def worker(words_queue, results_queue):
            """工作线程函数"""
            while True:
                try:
                    word = words_queue.get_nowait()
                except:
                    break

                audio_path = self._save_word_audio_local(word)
                results_queue.put((word, audio_path))
                words_queue.task_done()

        # 创建队列
        words_queue = Queue()
        results_queue = Queue()

        # 填充任务队列
        for word in word_list:
            words_queue.put(word)

        # 创建并启动工作线程
        threads = []
        for _ in range(min(num_threads, len(word_list))):
            thread = threading.Thread(target=worker, args=(words_queue, results_queue))
            thread.start()
            threads.append(thread)

        # 等待所有任务完成
        words_queue.join()

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        # 收集结果
        results = {}
        while not results_queue.empty():
            word, audio_path = results_queue.get()
            results[word] = audio_path

        return results

    def _load_audio_file(self, file_path, word):
        """加载音频文件"""
        try:
            if not file_path or not os.path.exists(file_path):
                return None

            audio = AudioSegment.from_file(file_path)
            if len(audio) == 0:
                return None

            return audio

        except Exception as e:
            print(f"加载音频失败 [{word}]: {e}")
            return None

    @staticmethod
    def _create_silence(duration_ms):
        """生成静音片段"""
        return AudioSegment.silent(duration=duration_ms)

    def generate_audio(self, word_list, repeat_times=2, interval_ms=1000,
                       playback_speed=1.0, parallel=True, output_file="word_review_local.mp3"):
        """
        生成最终跟读音频

        :param word_list: 单词列表
        :param repeat_times: 重复次数
        :param interval_ms: 间隔时间(毫秒)
        :param playback_speed: 播放速度
        :param parallel: 是否并行处理
        :param output_file: 输出文件名
        """
        if not self.engine:
            print("TTS引擎未初始化，无法生成音频")
            return

        print(f"开始处理 {len(word_list)} 个单词...")

        # 第一步：生成所有单词的音频文件
        print("\n" + "=" * 50)
        print("第一步：生成单词音频文件")
        print("=" * 50)

        if parallel:
            audio_paths = self._generate_audio_parallel(word_list)
        else:
            audio_paths = {}
            for word in word_list:
                audio_paths[word] = self._save_word_audio_local(word)

        # 第二步：合并音频
        print("\n" + "=" * 50)
        print("第二步：合并音频文件")
        print("=" * 50)

        final_audio = AudioSegment.empty()
        silence = self._create_silence(interval_ms)

        successful_words = []
        failed_words = []

        for i, word in enumerate(word_list, 1):
            print(f"合并单词 ({i}/{len(word_list)}): {word}", end=" ")

            audio_path = audio_paths.get(word)
            if not audio_path or not os.path.exists(audio_path):
                print("❌ (无音频文件)")
                failed_words.append(word)
                continue

            word_audio = self._load_audio_file(audio_path, word)
            if not word_audio:
                print("❌ (加载失败)")
                failed_words.append(word)
                continue

            try:
                for _ in range(repeat_times):
                    final_audio += word_audio
                    final_audio += silence

                # 单词间间隔稍长
                final_audio += self._create_silence(500)
                print("✅")
                successful_words.append(word)

            except Exception as e:
                print(f"❌ (合并失败: {e})")
                failed_words.append(word)

        if len(successful_words) == 0:
            print("没有成功生成任何音频")
            return

        # 第三步：调整语速
        print("\n" + "=" * 50)
        print("第三步：处理最终音频")
        print("=" * 50)

        if playback_speed != 1.0 and len(final_audio) > 0:
            try:
                print(f"调整语速: {playback_speed}")
                final_audio = speedup(final_audio, playback_speed=playback_speed,
                                      chunk_size=150, crossfade=25)
            except Exception as e:
                print(f"语速调整失败: {e}")

        # 第四步：导出文件
        print("\n" + "=" * 50)
        print("第四步：导出音频文件")
        print("=" * 50)

        try:
            print(f"导出到: {output_file}")
            final_audio.export(output_file, format="mp3", bitrate="192k")

            # 统计信息
            duration_seconds = len(final_audio) / 1000
            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)

            print("\n" + "=" * 50)
            print("🎉 生成完成！")
            print("=" * 50)
            print(f"📁 输出文件: {output_file}")
            print(f"⏱️ 音频时长: {minutes}分{seconds}秒")
            print(f"✅ 成功单词: {len(successful_words)} 个")

            if failed_words:
                print(f"❌ 失败单词: {len(failed_words)} 个")
                print(f"   失败列表: {', '.join(failed_words)}")

            # 显示文件大小
            file_size = os.path.getsize(output_file) / (1024 * 1024)
            print(f"💾 文件大小: {file_size:.2f} MB")

        except Exception as e:
            print(f"导出失败: {e}")


def main():
    """主函数"""
    word_list = [
        "happen", "since", "break", "building", "wish", "festival", "language", "example", "healthy", "share",
        "taste", "company", "sound", "museum", "difficult", "close", "light", "stand", "late", "excite",
        "tomorrow", "mind", "forget", "anything", "order", "scientist", "heart", "fall", "collect", "history",
        "weather", "afraid", "protect", "catch", "seem", "chance", "improve", "culture", "wear", "return",
        "realize", "science", "develop", "village", "environment", "allow", "possible", "pick", "report",
        "note", "able", "news", "angry", "mainly", "arrive", "strong", "suddenly", "quite", "hurt", "head",
        "business", "invite", "laugh", "store", "encourage", "favorite", "plane", "ticket", "throw", "traffic",
        "join", "provide", "trouble", "meeting", "whole", "paint", "mobile", "newspaper", "library", "several",
        "middle", "agree", "dangerous", "mistake", "include", "create", "carefully", "spring", "carry", "smell"
    ]

    if not word_list:
        print("单词列表为空")
        return

    # 创建本地音频生成器
    print("正在初始化本地TTS引擎...")

    # 参数说明：
    # rate: 语速 (默认150，可以调整)
    # volume: 音量 (0.0-1.0)
    # voice_type: 语音类型，可选 'male'/'female'/None
    # voice_dir: 音频保存目录
    generator = LocalWordAudioGenerator(
        rate=150,  # 语速
        volume=1.0,  # 音量
        voice_type='female',  # 语音类型
        voice_dir='Speech_Local'  # 音频保存目录
    )

    # 生成音频
    generator.generate_audio(
        word_list=word_list,
        repeat_times=2,  # 每个单词重复次数
        interval_ms=1000,  # 重复间隔(毫秒)
        playback_speed=1.0,  # 播放速度
        parallel=True,  # 并行处理
        output_file="word_review_local.mp3"  # 输出文件名
    )


if __name__ == "__main__":
    main()
