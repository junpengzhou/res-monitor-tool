# -*- coding: utf-8 -*-
from PIL import Image
import random


def main():
    def generate_random_image(width, height, save_path="random_image.png"):
        # 创建随机像素数据 (RGB)
        pixels = [
            (random.randint(0, 255),  # R
             random.randint(0, 255),  # G
             random.randint(0, 255)  # B
             ) for _ in range(width * height)
        ]

        # 创建新图像
        img = Image.new("RGB", (width, height))
        img.putdata(pixels)

        # 保存图片
        img.save(save_path)
        print(f"图片已保存至 {save_path}", flush=True)
        return img

    # 使用示例：生成500x300像素的随机图片
    generate_random_image(2000, 2000)


if __name__ == "__main__":
    main()
