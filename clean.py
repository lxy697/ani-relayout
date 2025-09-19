import os
import shutil

# 要清理的文件夹列表（脚本目录下）
FOLDERS_TO_CLEAN = ["pre", "fin", "input", "output"]

def clean_folder(folder_path):
    """
    删除文件夹下的所有内容，但保留文件夹本身
    """
    if not os.path.exists(folder_path):
        print(f"{folder_path} 不存在，跳过")
        return

    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)
        try:
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        except Exception as e:
            print(f"删除 {item_path} 时出错: {e}")
    print(f"{folder_path} 已清理完成")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for folder_name in FOLDERS_TO_CLEAN:
        folder_path = os.path.join(script_dir, folder_name)
        clean_folder(folder_path)
