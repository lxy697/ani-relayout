import os
import zipfile
import shutil

# 文件夹变量
OUTPUT_DIR = "output"    # 存放 CBZ 的目录
FINAL_DIR = "final"      # 临时解压目录
FIN_DIR = "fin"          # 最终 CBZ 输出目录
FINAL_CBZ_NAME = "final.cbz"  # 最终生成的 CBZ 文件名

def unzip_all_cbz_to_final(output_dir, final_dir):
    """
    将 output 目录下的所有 CBZ 文件解压到 final 目录，
    每个 CBZ 在 final 下新建同名文件夹
    """
    os.makedirs(final_dir, exist_ok=True)
    for item in os.listdir(output_dir):
        item_path = os.path.join(output_dir, item)
        if os.path.isfile(item_path) and item_path.lower().endswith('.cbz'):
            folder_name = os.path.splitext(item)[0]
            folder_path = os.path.join(final_dir, folder_name)
            os.makedirs(folder_path, exist_ok=True)
            with zipfile.ZipFile(item_path, 'r') as zipf:
                zipf.extractall(folder_path)
            print(f"已解压 {item_path} -> {folder_path}")

def zip_final_to_cbz(final_dir, fin_dir, final_cbz_name):
    """
    将 final 文件夹压缩成 CBZ 并输出到 fin 文件夹
    """
    os.makedirs(fin_dir, exist_ok=True)
    final_cbz_path = os.path.join(fin_dir, final_cbz_name)

    with zipfile.ZipFile(final_cbz_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(final_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, final_dir)
                zipf.write(file_path, arcname)
    print(f"已生成最终 CBZ: {final_cbz_path}")

def cleanup_final(final_dir):
    """
    删除临时 final 文件夹
    """
    if os.path.exists(final_dir):
        shutil.rmtree(final_dir)
        print(f"已删除临时文件夹: {final_dir}")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, OUTPUT_DIR)
    final_dir = os.path.join(script_dir, FINAL_DIR)
    fin_dir = os.path.join(script_dir, FIN_DIR)

    unzip_all_cbz_to_final(output_dir, final_dir)
    zip_final_to_cbz(final_dir, fin_dir, FINAL_CBZ_NAME)
    cleanup_final(final_dir)
