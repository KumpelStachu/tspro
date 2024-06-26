from ffmpeg_progress_yield import FfmpegProgress
from datetime import datetime, timedelta
from typing import Any
import subprocess
import argparse
import json
import sys
import re
import os

if sys.platform == 'win32':
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    sp_flags: dict[str, Any] = {'startupinfo': si}
else:
    sp_flags = {}

prefix_re = r'[a-zA-Z0-9_-]'
nl = '\n'

def probe(filename: str) -> dict:
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', filename]
    return json.loads(subprocess.check_output(cmd, **sp_flags).decode())

def ensure_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **sp_flags)
        subprocess.run(['ffprobe', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **sp_flags)

        return True
    except FileNotFoundError:
        print('Error: ffmpeg not found')
        
        if sys.platform == 'win32':
            print('Download ffmpeg from https://ffmpeg.org/download.html')
        elif sys.platform == 'linux':
            print('Run `sudo apt install ffmpeg`')
        elif sys.platform == 'darwin':
            print('Run `brew install ffmpeg`')
        else:
            print('Install ffmpeg from https://ffmpeg.org/download.html')

        return False

def file_name(file: str) -> str:
    return file.split('/')[-1]
    
def escape(value: str) -> str:
    return value.replace(':', '\\:').replace('"', '\\"').replace('\\', '\\\\')

def process(filename: str, suffix:str, size:float, margin:float, position_x:str, position_y:str, font:str, color:str, border:str, opacity:float, gpu=False, quality=14) -> list[str] | None:
    try:
        info = probe(filename)
        stream = next(filter(lambda s: s['codec_type'] == 'video', info['streams']))
    except subprocess.CalledProcessError:
        print(f'Error: invalid input file {filename}')
        return

    try:
        creation_time = datetime.strptime(stream['tags']['creation_time'], "%Y-%m-%dT%H:%M:%S.%fZ").timestamp()
    except KeyError:
        print(f'Warning: no creation time for {filename}, using file creation time')
        creation_time = os.path.getctime(filename)
    
    width = stream['width']
    height = stream['height']
    scaled_size = size * min(width, height) / 300

    x = margin * scaled_size / size
    if position_x == 'center':
        x = f'(W-text_w)/2'
    elif position_x == 'right':
        x = f'W-text_w-{x}'

    y = margin * scaled_size / size
    if position_y == 'center':
        y = f'(H-text_h)/2'
    elif position_y == 'bottom':
        y = f'H-text_h-{y}'

    codec = stream['codec_name']
    qp = min((101 - quality) // (2 if gpu else 1.7), 51)
    output = re.sub(r'\.(\w+)$', fr'{suffix}.\1', filename)

    input_flags = [
        '-hwaccel', 'cuda', 
        # '-hwaccel_output_format', 'cuda', 
        '-c:v', f'{codec}_cuvid',
        ] if gpu else []
    
    output_flags = [
        '-c:v', f'{codec}_nvenc',
        ] if gpu else []
    
    drawtext = {
        'alpha': opacity/100,
        # TODO: Fix font path for Windows (detect fontconfig)
        ('fontfile' if '.' in font else 'font'): font.replace('\\', '/'),
        'fontcolor': color,
        'fontsize': scaled_size,
        'bordercolor': border,
        'borderw': scaled_size/16,
        'x': x,
        'y': y,
        'text': fr'%{{pts:localtime:{int(creation_time)}}}',
    }

    return ['ffmpeg', '-y', '-hide_banner',
            *input_flags, '-i', filename,
            '-c:a', 'copy',
            '-qp', str(qp),
            '-vf', f'drawtext="{":".join(f"{escape(k)}={escape(str(v))}" for k, v in drawtext.items())}',
            *output_flags, output]

def handle_cli(input_files: list[str], verbose=True, **kwargs):
    if not ensure_ffmpeg():
        exit(1)

    if not verbose:
        from tqdm import tqdm

    for filename in input_files:
        if cmd := process(filename, **kwargs):
            if verbose:
                print(f'Processing {filename}')
                subprocess.run(cmd)
            else:
                ff = FfmpegProgress(cmd)
                with tqdm(total=100, position=0, desc=file_name(filename)) as pbar: # type: ignore
                    for progress in ff.run_command_with_progress(popen_kwargs=sp_flags):
                        pbar.update(progress - pbar.n)

def handle_gui():
    from guizero import App, PushButton, Box, TextBox, Text, Combo, CheckBox
    from tkinter.filedialog import askopenfilenames
    from tkinter.ttk import Progressbar
    from threading import Thread

    ff: FfmpegProgress | None = None

    def download_ffmpeg():
        if sys.platform == 'win32':
            from tempfile import mkdtemp
            import requests
            import zipfile
            import shutil
            import io

            url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
            response = requests.get(url)
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                print('Extracting ffmpeg')
                temp = mkdtemp()
                bin = 'ffmpeg-master-latest-win64-gpl/bin'
                z.extractall(temp, [f'{bin}/ffmpeg.exe', f'{bin}/ffprobe.exe'])
                shutil.move(f'{temp}/{bin}/ffmpeg.exe', 'ffmpeg.exe')
                shutil.move(f'{temp}/{bin}/ffprobe.exe', 'ffprobe.exe')
                shutil.rmtree(temp)
        else:
            print('Error: unsupported platform')

    def isfloat(value: str) -> bool:
        try:
            float(value)
            return True
        except ValueError:
            return False

    def probable(file: str) -> bool:
        try:
            probe(file)
            return True
        except subprocess.CalledProcessError:
            return False
        
    def td_str(td: timedelta) -> str:
        return f'{td.seconds//3600:02}:{td.seconds//60%60:02}:{td.seconds%60:02}'
        
    def start_work(videos: list[str]):
        nonlocal ff
        
        for file in videos:
            ff_start = datetime.now()
            progress_text.value = file_name(file)
            if cmd := process(file, suffix_textbox.value, float(size_textbox.value), float(margin_textbox.value), horizontal_textbox.value, vertical_textbox.value, font_textbox.value, color_textbox.bg, border_textbox.bg, float(opacity_textbox.value), bool(cuda_checkbox.value), int(quality_textbox.value)):
                try:
                    ff = FfmpegProgress(cmd)
                    for progress in ff.run_command_with_progress(popen_kwargs=sp_flags):
                        time = datetime.now() - ff_start
                        eta = time * (0 if progress == 0 else (100 - progress) / progress)
                        progress_info.value = f"[{progress:.2f}%] {td_str(time)} (ETA {td_str(eta)})"
                        progress_bar['value'] = progress
                except RuntimeError:
                    if ff:
                        app.error("Error", f"Failed to process {file_name(file)}")
                    break
                except ValueError: break
                finally:
                    ff = None
        else:
            app.info("Info", "Operation completed")
        
        cancel_button.disable()
        start_button.enable()
        progress_box.hide()
        
    def start():
        if not suffix_textbox.value:
            app.error("Error", "Suffix is empty")
            return
        
        if not re.match(prefix_re, suffix_textbox.value):
            app.error("Error", "Suffix is not alphanumeric")
            return
        
        files = askopenfilenames(parent=app.master, title="Select videos", filetypes=[("Videos", "*.mp4")], initialdir=".")
        if not files:
            app.warn("Warning", "No files selected")
            return
        
        videos, errors = [], []
        for file in files:
            to = videos if probable(file) else errors
            to.append(file)
        
        if errors:
            app.warn("Warning", f"Invalid files:\n{nl.join(map(file_name, videos))}")

        if not videos:
            app.warn("Warning", "No valid files selected")
        elif app.yesno("Confirmation", f"Process {len(videos)} file{'' if len(videos)==1 else 's'}?\n{nl.join(map(file_name, videos))}"):
            cancel_button.enable()
            start_button.disable()
            progress_box.show()
            progress_bar['value'] = 0
            app.show()

            nonlocal ff
            if ff:
                app.error("Error", "Operation already in progress")
                return
            
            Thread(target=start_work, args=(videos,)).start()
        else:
            app.info("Info", "Operation cancelled")

    def cancel():
        nonlocal ff
        if ff:
            ff_copy = ff
            ff = None
            ff_copy.quit_gracefully()
            app.info("Info", "Operation cancelled")

        cancel_button.disable()
        start_button.enable()
        progress_box.hide()

    def select_color():
        value = app.select_color(color_textbox.bg)
        if value:
            color_textbox.bg = value

    def fonts_folder() -> str:
        if sys.platform == 'win32':
            return "C:/Windows/Fonts"
        if sys.platform == 'linux':
            return "/usr/share/fonts"
        if sys.platform == 'darwin':
            return "/Library/Fonts"
        return "."

    def select_font():
        value = app.select_file(folder=fonts_folder(), title="Select font", filetypes=[("Fonts", ".ttf .otf .woff .woff2 .tcc")])
        if value:
            font_textbox.value = value
            update_font()
        else:
            app.warn("Warning", "No font selected")

    def select_border():
        value = app.select_color(border_textbox.bg)
        if value:
            border_textbox.bg = value

    def update_example():
        suffix_example.value = f"video.mp4 => video{suffix_textbox.value}.mp4"

    def update_font():
        font_textbox.font = font_textbox.value

    def validate_float(initial: float, textbox: TextBox, min:float|None=0, max:float|None=None):
        prev = initial
        def f():
            nonlocal prev
            if isfloat(textbox.value):
                value = float(textbox.value)
                if (min is None or min <= value) and (max is None or value <= max):
                    prev = value
            else:
                textbox.value = str(prev)
        textbox.update_command(f)

    def block_input(textbox: TextBox):
        def f():
            textbox.value = ""
        textbox.update_command(f)

    def cuda_check():
        if cuda_checkbox.value:
            cuda_checkbox.value = app.yesno("Continue?", "Make sure you have NVIDIA GPU with NVENC support")

    def download_button():
        download_ffmpeg()
        app.info("Info", "FFmpeg downloaded")

    def when_closed():
        if ff:
            ff.quit()
        app.destroy()

    def center(win):
        # Stolen from https://stackoverflow.com/a/10018670
        win.update_idletasks()
        width = win.winfo_width()
        frm_width = win.winfo_rootx() - win.winfo_x()
        win_width = width + 2 * frm_width
        height = win.winfo_height()
        titlebar_height = win.winfo_rooty() - win.winfo_y()
        win_height = height + titlebar_height + frm_width
        x = win.winfo_screenwidth() // 2 - win_width // 2
        y = win.winfo_screenheight() // 2 - win_height // 2
        win.geometry('{}x{}+{}+{}'.format(width, height, x, y))
        win.deiconify()

    app = App(title="stamper")
    app.when_closed = when_closed
    app.tk.resizable(False, False)
    center(app.tk)

    settings_box = Box(app, width="fill", layout="grid")

    Text(settings_box, text="File suffix", grid=[0, 0], align="left")
    suffix_textbox = TextBox(settings_box, text="_ts", grid=[1, 0], command=update_example, align="left")
    suffix_example = Text(settings_box, grid=[2, 0], align="left")

    Text(settings_box, text="Font family", grid=[0, 1], align="left")
    font_textbox = TextBox(settings_box, text="Arial", grid=[1, 1], command=update_font, align="left")
    PushButton(settings_box, text="Select", grid=[2, 1], command=select_font, align="left", pady=0)

    Text(settings_box, text="Text color", grid=[0, 2], align="left")
    color_textbox = TextBox(settings_box, grid=[1, 2], align="left")
    block_input(color_textbox)
    color_textbox.when_clicked = select_color
    color_textbox.bg = "#FFFFFF"

    Text(settings_box, text="Border color", grid=[0, 3], align="left")
    border_textbox = TextBox(settings_box, grid=[1, 3], align="left")
    block_input(border_textbox)
    border_textbox.when_clicked = select_border
    border_textbox.bg = "#000000"

    Text(settings_box, text="Text size", grid=[0, 4], align="left")
    size_textbox = TextBox(settings_box, text="20", grid=[1, 4], align="left")
    validate_float(24, size_textbox, 0, 100)

    Text(settings_box, text="Overlay opacity", grid=[0, 5], align="left")
    opacity_textbox = TextBox(settings_box, text="100", grid=[1, 5], align="left")
    validate_float(100, opacity_textbox, 0, 100)

    Text(settings_box, text="Overlay margin", grid=[0, 6], align="left")
    margin_textbox = TextBox(settings_box, text="10", grid=[1, 6], align="left")
    validate_float(10, margin_textbox, 0)

    Text(settings_box, text="Horizontal position", grid=[0, 7], align="left")
    horizontal_textbox = Combo(settings_box, options=['left', 'center', 'right'], grid=[1, 7], align="left", width="fill")

    Text(settings_box, text="Vertical position", grid=[0, 8], align="left")
    vertical_textbox = Combo(settings_box, selected='bottom', options=['top', 'center', 'bottom'], grid=[1, 8], align="left", width="fill")

    Text(settings_box, text="Quality", grid=[0, 9], align="left")
    quality_textbox = TextBox(settings_box, text="72", grid=[1, 9], align="left")
    validate_float(12, quality_textbox, 0, 100)

    cuda_checkbox = CheckBox(settings_box, text="Use NVIDIA GPU acceleration", grid=[0, 10, 3, 1], align="left", width="fill", command=cuda_check)

    PushButton(settings_box, text="Download ffmpeg (recommended for Windows)", grid=[0, 11, 3, 1], align="left", command=download_button)

    # TODO: add load/save settings buttons

    buttons_box = Box(app, width="fill", align="bottom")
    cancel_button = PushButton(buttons_box, text="Cancel", align="right", enabled=False, command=cancel)
    start_button = PushButton(buttons_box, text="Start", align="right", command=start)

    progress_box = Box(buttons_box, width="fill", align="bottom", visible=False)
    progress_text = Text(progress_box, text="Progress")
    progress_info = Text(progress_box, text="Progress", size=10)
    progress_bar = Progressbar(progress_box.tk)
    progress_box.add_tk_widget(progress_bar, width="fill")

    if not ensure_ffmpeg():
        if app.yesno("Error", "FFmpeg not found, download now?"):
            download_ffmpeg()
            app.info("Info", "FFmpeg downloaded")
        else:
            app.destroy()

    update_font()
    update_example()
    app.display()

def main():
    parser = argparse.ArgumentParser(prog='stamper', description='Add timestamp overlay to video')
    parser.add_argument('input_files', help='Input video files', nargs='*')
    parser.add_argument('-v', '--verbose', help='Verbose output', action='store_true')
    parser.add_argument('-e', '--suffix', help='Output file suffix', default='_ts')
    parser.add_argument('-f', '--font', help='Font family', default='Arial')
    parser.add_argument('-c', '--color', help='Text color', default='white')
    parser.add_argument('-b', '--border', help='Border color', default='black')
    parser.add_argument('-s', '--size', help='Text size', default=20, type=float)
    parser.add_argument('-o', '--opacity', help='Overlay opacity', default=100, type=float)
    parser.add_argument('-m', '--margin', help='Overlay margin', default=10, type=float)
    parser.add_argument('-x', '--position-x', help='Horizontal position', default='left', choices=['left', 'center', 'right'])
    parser.add_argument('-y', '--position-y', help='Vertical position', default='bottom', choices=['top', 'center', 'bottom'])
    parser.add_argument('-q', '--quality', help='Quality', default=72, type=int)
    parser.add_argument('-g', '--gpu', help='Use NVIDIA GPU acceleration', action='store_true')

    args = parser.parse_args()
    if args.input_files:
        handle_cli(**vars(args))
    else:
        handle_gui()

if __name__ == '__main__':
    main()
