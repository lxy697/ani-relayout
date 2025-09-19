import os
import zipfile

# 要压缩的目录名（脚本所在目录下的子文件夹）
FOLDER_NAME = "pre"

# 输出目录（脚本目录下的子文件夹，可以自定义）
OUTPUT_DIR = "input"

def zip_folder_to_cbz(folder_path, output_dir):
    """
    将指定文件夹压缩为同名cbz文件，输出到指定目录
    """
    folder_path = os.path.abspath(folder_path)
    os.makedirs(output_dir, exist_ok=True)  # 输出目录不存在则创建
    folder_name = os.path.basename(folder_path)
    cbz_path = os.path.join(output_dir, folder_name + '.cbz')

    with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, folder_path)
                zipf.write(file_path, arcname)

    print(f"已生成: {cbz_path}")

def compress_all_folders_in_dir(folder_name, output_dir):
    """
    压缩指定目录下的所有子文件夹为 cbz，并输出到指定目录
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))  # 脚本目录
    target_dir = os.path.join(script_dir, folder_name)
    output_dir = os.path.join(script_dir, output_dir)

    if not os.path.exists(target_dir):
        print(f"{target_dir} 不存在！")
        return

    for item in os.listdir(target_dir):
        item_path = os.path.join(target_dir, item)
        if os.path.isdir(item_path):
            zip_folder_to_cbz(item_path, output_dir)

if __name__ == "__main__":
    compress_all_folders_in_dir(FOLDER_NAME, OUTPUT_DIR)
