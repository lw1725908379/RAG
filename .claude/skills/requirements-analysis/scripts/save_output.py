# -*- coding: utf-8 -*-
"""
RATP-Engine 输出保存脚本
用于保存原子化拆解结果到 JSON 文件
"""
import json
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path


def save_atoms_to_json(atoms: list, output_dir: str = None, prefix: str = "atoms") -> str:
    """
    保存原子化结果到 JSON 文件

    Args:
        atoms: 原子功能列表
        output_dir: 输出目录，默认当前目录
        prefix: 文件名前缀

    Returns:
        保存的文件路径
    """
    if output_dir is None:
        output_dir = os.getcwd()

    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    # 构建输出结构
    output_data = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "atom_count": len(atoms),
            "version": "1.0"
        },
        "atoms": atoms
    }

    # 保存文件
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"已保存 {len(atoms)} 个原子功能到: {filepath}")
    return filepath


def load_atoms_from_json(filepath: str) -> list:
    """
    从 JSON 文件加载原子功能列表

    Args:
        filepath: JSON 文件路径

    Returns:
        原子功能列表
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("atoms", [])


def get_latest_output(output_dir: str = None, prefix: str = "atoms") -> str:
    """
    获取最新的输出文件路径

    Args:
        output_dir: 输出目录
        prefix: 文件名前缀

    Returns:
        最新文件的路径，如果没有则返回 None
    """
    if output_dir is None:
        output_dir = os.getcwd()

    pattern = f"{prefix}_*.json"
    files = sorted(Path(output_dir).glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)

    return str(files[0]) if files else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RATP-Engine 输出保存工具")
    parser.add_argument("--atoms", type=str, help="JSON 字符串格式的原子功能列表")
    parser.add_argument("--file", type=str, help="输入 JSON 文件路径")
    parser.add_argument("--output-dir", type=str, default="data/test_requirements", help="输出目录")
    parser.add_argument("--prefix", type=str, default="atoms", help="文件名前缀")

    args = parser.parse_args()

    atoms = []

    if args.atoms:
        # 从命令行参数读取
        atoms = json.loads(args.atoms)
    elif args.file:
        # 从文件读取
        with open(args.file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            atoms = data.get("atoms", [])
    else:
        print("请提供 --atoms 或 --file 参数")
        sys.exit(1)

    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)

    # 保存
    filepath = save_atoms_to_json(atoms, args.output_dir, args.prefix)
    print(f"文件路径: {filepath}")
