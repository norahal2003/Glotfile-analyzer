import struct, json, hashlib, threading
from pathlib import Path
from tkinter import *
from tkinter import ttk, filedialog, messagebox


# ─────────────────────────────────────────────
#  core engine (same logic as colab version)
# ─────────────────────────────────────────────

def fmt_bytes(n):
    if n < 1024:    return f'{n} B'
    if n < 1024 ** 2: return f'{n / 1024:.1f} KB'
    return f'{n / 1024 ** 2:.2f} MB'


def fix_mp4_offsets(mp4_bytes, subtracted):
    if subtracted == 0:
        return mp4_bytes
    fixed = bytearray(mp4_bytes)
    for box_type, esize in [(b'stco', 4), (b'co64', 8)]:
        pos = 0
        while pos < len(fixed) - 8:
            p = fixed.find(box_type, pos)
            if p == -1: break
            if p >= 4:
                bsize = int.from_bytes(fixed[p - 4:p], 'big')
                if 16 <= bsize <= len(fixed):
                    count = int.from_bytes(fixed[p - 4 + 12:p - 4 + 16], 'big')
                    for i in range(count):
                        op = p - 4 + 16 + i * esize
                        if op + esize > len(fixed): break
                        old = int.from_bytes(fixed[op:op + esize], 'big')
                        fixed[op:op + esize] = max(0, old - subtracted).to_bytes(esize, 'big')
            pos = p + 1
    return bytes(fixed)


def detect_formats(data):
    results = []
    seen = set()

    def add(fid, label, ext, offset, chunk):
        if fid not in seen:
            results.append({'id': fid, 'label': label, 'ext': ext, 'offset': offset, 'data': chunk})
            seen.add(fid)

    pdf_start = data.find(b'%PDF')
    mdat_pos = data.find(b'mdat')
    mdat_start = (mdat_pos + 4) if mdat_pos != -1 else None
    ftyp_pos = data.find(b'ftyp')
    mp4_start = (ftyp_pos - 4) if (ftyp_pos != -1 and ftyp_pos >= 4) else None

    def inside(offset):
        if pdf_start != -1 and offset > pdf_start:   return True
        if mdat_start and offset >= mdat_start:       return True
        return False

    if data[:4] == b'\x00\x00\x01\x00':
        add('ico', 'ICO icon', '.ico', 0, data)

    pos = 0
    while True:
        p = data.find(b'\x89PNG\r\n\x1a\n', pos)
        if p == -1: break
        if not inside(p):
            iend = data.find(b'IEND', p)
            end = (iend + 8) if iend != -1 else len(data)
            add('png', 'PNG image', '.png', p, data[p:end]);
            break
        pos = p + 1

    pos = 0
    while True:
        p = data.find(b'\xff\xd8\xff', pos)
        if p == -1: break
        if not inside(p):
            ffd9 = data.find(b'\xff\xd9', p + 3)
            end = (ffd9 + 2) if ffd9 != -1 else len(data)
            add('jpg', 'JPEG image', '.jpg', p, data[p:end]);
            break
        pos = p + 1

    pos = 0
    while True:
        p = data.find(b'GIF8', pos)
        if p == -1: break
        if not inside(p):
            add('gif', 'GIF image', '.gif', p, data[p:]);
            break
        pos = p + 1

    riff = data.find(b'RIFF')
    if riff != -1 and data[riff + 8:riff + 12] == b'WEBP' and not inside(riff):
        add('webp', 'WebP image', '.webp', riff, data[riff:])

    if pdf_start != -1:
        add('pdf', 'PDF document', '.pdf', pdf_start, data[pdf_start:])

    if mp4_start is not None:
        add('mp4', 'MP4 video', '.mp4', mp4_start, fix_mp4_offsets(data[mp4_start:], mp4_start))

    if riff != -1 and data[riff + 8:riff + 12] == b'AVI ':
        add('avi', 'AVI video', '.avi', riff, data[riff:])

    mkv = data.find(b'\x1a\x45\xdf\xa3')
    if mkv != -1:
        add('mkv', 'MKV video', '.mkv', mkv, data[mkv:])

    eocd = data.rfind(b'PK\x05\x06')
    if eocd != -1:
        total = int.from_bytes(data[eocd + 8:eocd + 10], 'little')
        pk = data.find(b'PK\x03\x04')
        if total == 0:
            add('zip', 'ZIP archive', '.zip', 0, data)
        elif pk != -1:
            add('zip', 'ZIP archive', '.zip', pk, data[pk:])
        else:
            cd_off = int.from_bytes(data[eocd + 16:eocd + 20], 'little')
            zip_start = max(0, eocd - cd_off)
            add('zip', 'ZIP archive', '.zip', zip_start, data[zip_start:])

    id3 = data.find(b'ID3')
    if id3 != -1 and not inside(id3):
        add('mp3', 'MP3 audio', '.mp3', id3, data[id3:])

    if riff != -1 and data[riff + 8:riff + 12] == b'WAVE':
        add('wav', 'WAV audio', '.wav', riff, data[riff:])

    rar = data.find(b'Rar!')
    if rar != -1:
        add('rar', 'RAR archive', '.rar', rar, data[rar:])

    sz = data.find(b'7z\xbc\xaf')
    if sz != -1:
        add('7z', '7-Zip archive', '.7z', sz, data[sz:])

    return results


def get_fmt(data, name):
    if data[:8] == b'\x89PNG\r\n\x1a\n':                              return 'png'
    if data[:3] == b'\xff\xd8\xff':                                    return 'jpg'
    if data[:4] == b'%PDF':                                            return 'pdf'
    if data[:2] == b'PK' and data[2] in (3, 5, 7):                      return 'zip'
    if len(data) >= 8 and data[4:8] == b'ftyp':                       return 'mp4'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'AVI ': return 'avi'
    if data[:4] == b'\x1a\x45\xdf\xa3':                                return 'mkv'
    if Path(name).suffix.lower() == '.mov':                            return 'mov'
    return 'unknown'


def trim_carrier(data, fmt):
    if fmt == 'png':
        i = data.rfind(b'IEND')
        return data[:i + 8] if i != -1 else data
    if fmt == 'jpg':
        i = data.rfind(b'\xff\xd9')
        return data[:i + 2] if i != -1 else data
    return data


# ─────────────────────────────────────────────
#  colours & fonts
# ─────────────────────────────────────────────
BG = '#0f0f1a'
SURFACE = '#1a1a2e'
BORDER = '#2a2a4a'
TEXT = '#e8e8f0'
MUTED = '#8888aa'
ACCENT = '#7c3aed'
GREEN = '#059669'
ORANGE = '#d97706'
RED = '#dc2626'

FMT_COLOR = {
    'pdf': '#f87171', 'png': '#60a5fa', 'jpg': '#60a5fa', 'gif': '#60a5fa',
    'webp': '#60a5fa', 'ico': '#c084fc', 'mp4': '#fb923c', 'avi': '#fb923c',
    'mkv': '#fb923c', 'mov': '#fb923c', 'zip': '#fbbf24', 'rar': '#fbbf24',
    '7z': '#fbbf24', 'mp3': '#34d399', 'wav': '#34d399',
}
FMT_ICON = {
    'pdf': '📄', 'png': '🖼', 'jpg': '🖼', 'gif': '🖼', 'webp': '🖼', 'ico': '🎨',
    'mp4': '🎬', 'avi': '🎬', 'mkv': '🎬', 'mov': '🎬',
    'zip': '🗜', 'rar': '🗜', '7z': '🗜', 'mp3': '🎵', 'wav': '🎵',
}

# ─────────────────────────────────────────────
#  main window
# ─────────────────────────────────────────────
root = Tk()
root.title('Polyglot Tool')
root.configure(bg=BG)
root.geometry('720x580')
root.resizable(True, True)

# ttk style
style = ttk.Style()
style.theme_use('default')
style.configure('TNotebook', background=BG, borderwidth=0)
style.configure('TNotebook.Tab', background=SURFACE, foreground=MUTED,
                padding=[16, 8], font=('Consolas', 10, 'bold'), borderwidth=0)
style.map('TNotebook.Tab',
          background=[('selected', ACCENT)],
          foreground=[('selected', 'white')])
style.configure('TFrame', background=BG)

# ── notebook tabs ──────────────────────────────
nb = ttk.Notebook(root)
nb.pack(fill=BOTH, expand=True, padx=10, pady=10)

tab_analyze = Frame(nb, bg=BG)
tab_create = Frame(nb, bg=BG)
nb.add(tab_analyze, text='  🔍 Analyze  ')
nb.add(tab_create, text='  ✨ Create  ')


# ─────────────────────────────────────────────
#  helpers to make widgets
# ─────────────────────────────────────────────
def label(parent, text, color=TEXT, size=10, bold=False, pady=0):
    font = ('Consolas', size, 'bold' if bold else 'normal')
    return Label(parent, text=text, bg=BG, fg=color, font=font, pady=pady)


def btn(parent, text, cmd, color=ACCENT, width=18):
    b = Button(parent, text=text, command=cmd, bg=color, fg='white',
               font=('Consolas', 10, 'bold'), relief=FLAT, cursor='hand2',
               activebackground=ACCENT, activeforeground='white',
               padx=12, pady=6, width=width, bd=0)
    b.bind('<Enter>', lambda e: b.config(bg='#6d28d9'))
    b.bind('<Leave>', lambda e: b.config(bg=color))
    return b


def card(parent, pady=4):
    f = Frame(parent, bg=SURFACE, bd=0, highlightthickness=1,
              highlightbackground=BORDER)
    f.pack(fill=X, padx=16, pady=pady)
    return f


def log(widget, msg, color=TEXT):
    widget.config(state=NORMAL)
    widget.insert(END, msg + '\n', color)
    widget.see(END)
    widget.config(state=DISABLED)


# ─────────────────────────────────────────────
#  ANALYZE TAB
# ─────────────────────────────────────────────
Label(tab_analyze, text='Analyze & Extract', bg=BG, fg=TEXT,
      font=('Consolas', 14, 'bold')).pack(pady=(16, 2))
Label(tab_analyze, text='pick a file → see every format inside → save each one',
      bg=BG, fg=MUTED, font=('Consolas', 9)).pack(pady=(0, 12))

# drop/pick area
pick_frame = Frame(tab_analyze, bg=SURFACE, highlightthickness=1,
                   highlightbackground=BORDER)
pick_frame.pack(fill=X, padx=16, pady=4)

a_file_var = StringVar(value='no file selected')
Label(pick_frame, textvariable=a_file_var, bg=SURFACE, fg=MUTED,
      font=('Consolas', 9), pady=8, wraplength=500).pack(side=LEFT, padx=12)


def pick_analyze():
    path = filedialog.askopenfilename(title='pick any file')
    if not path: return
    a_file_var.set(path)
    run_analyze(path)


btn(pick_frame, '📂  Browse', pick_analyze, width=14).pack(side=RIGHT, padx=8, pady=8)

# output log
out_frame = Frame(tab_analyze, bg=BG)
out_frame.pack(fill=BOTH, expand=True, padx=16, pady=8)

a_log = Text(out_frame, bg=SURFACE, fg=TEXT, font=('Consolas', 9),
             relief=FLAT, state=DISABLED, wrap=WORD,
             highlightthickness=1, highlightbackground=BORDER)
a_log.pack(side=LEFT, fill=BOTH, expand=True)
sb = Scrollbar(out_frame, command=a_log.yview, bg=BG, troughcolor=SURFACE,
               relief=FLAT, width=8)
sb.pack(side=RIGHT, fill=Y)
a_log.config(yscrollcommand=sb.set)

# text tags for colors
for name, color in [*FMT_COLOR.items(),
                    ('green', GREEN), ('orange', ORANGE), ('muted', MUTED),
                    ('red', RED), ('accent', ACCENT), ('white', 'white')]:
    a_log.tag_config(name, foreground=color)


def run_analyze(path):
    a_log.config(state=NORMAL)
    a_log.delete('1.0', END)
    a_log.config(state=DISABLED)

    def work():
        try:
            data = open(path, 'rb').read()
            fname = Path(path).name
            stem = Path(path).stem

            log(a_log, f'  file  : {fname}')
            log(a_log, f'  size  : {fmt_bytes(len(data))}')
            log(a_log, f'  bytes : {" ".join(f"{b:02X}" for b in data[:20])} …', 'muted')
            log(a_log, '  ' + '─' * 50, 'muted')

            detected = detect_formats(data)

            if not detected:
                log(a_log, '  no recognised format found', 'orange')
                return

            tag = f'polyglot — {len(detected)} formats' if len(detected) > 1 else 'single format'
            log(a_log, f'  {tag}\n', 'accent')

            save_dir = filedialog.askdirectory(title='where to save extracted files?')
            if not save_dir:
                log(a_log, '  no folder chosen — nothing saved', 'orange')
                return

            for fmt in detected:
                out = str(Path(save_dir) / (stem + fmt['ext']))
                chunk = fmt['data']
                open(out, 'wb').write(chunk)
                icon = FMT_ICON.get(fmt['id'], '📁')
                color = fmt['id'] if fmt['id'] in FMT_COLOR else 'white'
                off = f'  (offset {fmt["offset"]:,})' if fmt['offset'] > 0 else ''
                log(a_log, f'  {icon}  {fmt["label"]:20s}  {fmt_bytes(len(chunk))}{off}', color)
                log(a_log, f'     saved → {out}', 'muted')

            log(a_log, '\n  done! ✓', 'green')

        except Exception as e:
            log(a_log, f'  error: {e}', 'red')

    threading.Thread(target=work, daemon=True).start()


# ─────────────────────────────────────────────
#  CREATE TAB
# ─────────────────────────────────────────────
Label(tab_create, text='Create Polyglot', bg=BG, fg=TEXT,
      font=('Consolas', 14, 'bold')).pack(pady=(16, 2))
Label(tab_create, text='combine files into one file that works as all of them',
      bg=BG, fg=MUTED, font=('Consolas', 9)).pack(pady=(0, 10))

COMBOS = {
    'PDF + Video + Image + ZIP': {
        'slots': [('🖼  Image (PNG/JPG)', 'img', ['png', 'jpg']),
                  ('📄  PDF file', 'pdf', ['pdf']),
                  ('🎬  Video file', 'vid', ['mp4', 'avi', 'mkv', 'mov']),
                  ('🗜  ZIP archive', 'zip', ['zip'])],
        'build': lambda c: trim_carrier(c['img'], get_fmt(c['img'], 'f.png')) + c['vid'] + c['pdf'] + c['zip'],
        'tips': ['image: open directly', 'pdf: rename .pdf', 'video: rename .mp4', 'zip: rename .zip'],
    },
    'PDF + Video + ZIP': {
        'slots': [('🖼  Image (PNG/JPG)', 'img', ['png', 'jpg']),
                  ('📄  PDF file', 'pdf', ['pdf']),
                  ('🎬  Video file', 'vid', ['mp4', 'avi', 'mkv', 'mov']),
                  ('🗜  ZIP archive', 'zip', ['zip'])],
        'build': lambda c: trim_carrier(c['img'], get_fmt(c['img'], 'f.png')) + c['vid'] + c['pdf'] + c['zip'],
        'tips': ['image: open directly', 'pdf: rename .pdf', 'video: rename .mp4', 'zip: rename .zip'],
    },
    'ZIP + Video + Image': {
        'slots': [('🖼  Image (PNG/JPG)', 'img', ['png', 'jpg']),
                  ('🎬  Video file', 'vid', ['mp4', 'avi', 'mkv', 'mov']),
                  ('🗜  ZIP archive', 'zip', ['zip'])],
        'build': lambda c: trim_carrier(c['img'], get_fmt(c['img'], 'f.png')) + c['vid'] + c['zip'],
        'tips': ['image: open directly', 'video: rename .mp4', 'zip: rename .zip'],
    },
    'Image + Video + PDF': {
        'slots': [('🖼  Image (PNG/JPG)', 'img', ['png', 'jpg']),
                  ('🎬  Video file', 'vid', ['mp4', 'avi', 'mkv', 'mov']),
                  ('📄  PDF file', 'pdf', ['pdf'])],
        'build': lambda c: trim_carrier(c['img'], get_fmt(c['img'], 'f.png')) + c['vid'] + c['pdf'],
        'tips': ['image: open directly', 'video: rename .mp4', 'pdf: rename .pdf'],
    },
    'PDF + Image': {
        'slots': [('🖼  Image (PNG/JPG)', 'img', ['png', 'jpg']),
                  ('📄  PDF file', 'pdf', ['pdf'])],
        'build': lambda c: trim_carrier(c['img'], get_fmt(c['img'], 'f.png')) + c['pdf'],
        'tips': ['image: open directly', 'pdf: rename .pdf'],
    },
    'Image + ZIP': {
        'slots': [('🖼  Image (PNG/JPG)', 'img', ['png', 'jpg']),
                  ('🗜  ZIP archive', 'zip', ['zip'])],
        'build': lambda c: trim_carrier(c['img'], get_fmt(c['img'], 'f.png')) + c['zip'],
        'tips': ['image: open directly', 'zip: rename .zip'],
    },
}

# combo picker
combo_var = StringVar(value=list(COMBOS.keys())[4])

cf = Frame(tab_create, bg=BG)
cf.pack(fill=X, padx=16)
Label(cf, text='combination:', bg=BG, fg=MUTED,
      font=('Consolas', 9)).pack(side=LEFT)
combo_menu = ttk.Combobox(cf, textvariable=combo_var,
                          values=list(COMBOS.keys()),
                          state='readonly', width=36,
                          font=('Consolas', 9))
style.configure('TCombobox', fieldbackground=SURFACE, background=SURFACE,
                foreground=TEXT, arrowcolor=TEXT, selectbackground=ACCENT)
combo_menu.pack(side=LEFT, padx=8)

# slot area
slots_frame = Frame(tab_create, bg=BG)
slots_frame.pack(fill=X, padx=16, pady=8)

slot_paths = {}  # key → filepath string


def refresh_slots(*_):
    for w in slots_frame.winfo_children():
        w.destroy()
    slot_paths.clear()
    combo = COMBOS[combo_var.get()]
    for (slabel, key, allowed) in combo['slots']:
        row = Frame(slots_frame, bg=SURFACE, highlightthickness=1,
                    highlightbackground=BORDER)
        row.pack(fill=X, pady=3)
        Label(row, text=slabel, bg=SURFACE, fg=TEXT,
              font=('Consolas', 9, 'bold'), width=22, anchor=W,
              padx=8, pady=6).pack(side=LEFT)
        var = StringVar(value='— not chosen —')
        slot_paths[key] = var
        Label(row, textvariable=var, bg=SURFACE, fg=MUTED,
              font=('Consolas', 8), anchor=W).pack(side=LEFT, fill=X, expand=True)

        def make_picker(k, a, v):
            def pick():
                ext_list = [(f'{x.upper()} file', f'*.{x}') for x in a]
                p = filedialog.askopenfilename(filetypes=ext_list + [('all', '*.*')])
                if not p: return
                fdata = open(p, 'rb').read()
                fmt = get_fmt(fdata, p)
                if fmt not in a:
                    messagebox.showerror('wrong type',
                                         f'expected {a}\ngot: {fmt} ({Path(p).name})')
                    return
                v.set(f'{Path(p).name}  ({fmt_bytes(len(fdata))})')
                v._path = p

            return pick

        b = Button(row, text='browse', command=make_picker(key, allowed, var),
                   bg=ACCENT, fg='white', font=('Consolas', 8, 'bold'),
                   relief=FLAT, cursor='hand2', padx=10, pady=4)
        b.bind('<Enter>', lambda e, b=b: b.config(bg='#6d28d9'))
        b.bind('<Leave>', lambda e, b=b: b.config(bg=ACCENT))
        b.pack(side=RIGHT, padx=8, pady=4)


combo_menu.bind('<<ComboboxSelected>>', refresh_slots)
refresh_slots()

# create button + log
btn(tab_create, '✨  Create Polyglot', lambda: run_create(), width=22).pack(pady=6)

c_log = Text(tab_create, bg=SURFACE, fg=TEXT, font=('Consolas', 9),
             relief=FLAT, state=DISABLED, wrap=WORD, height=7,
             highlightthickness=1, highlightbackground=BORDER)
c_log.pack(fill=X, padx=16, pady=(0, 10))
for name, color in [*FMT_COLOR.items(),
                    ('green', GREEN), ('orange', ORANGE),
                    ('muted', MUTED), ('red', RED), ('accent', ACCENT)]:
    c_log.tag_config(name, foreground=color)


def run_create():
    c_log.config(state=NORMAL);
    c_log.delete('1.0', END);
    c_log.config(state=DISABLED)
    combo = COMBOS[combo_var.get()]

    # collect files
    collected = {}
    for (slabel, key, allowed) in combo['slots']:
        var = slot_paths.get(key)
        if not var or not hasattr(var, '_path'):
            log(c_log, f'  missing: {slabel}', 'orange')
            return
        collected[key] = open(var._path, 'rb').read()

    def work():
        try:
            result = combo['build'](collected)
            img_name = Path(slot_paths['img']._path).stem
            out_path = filedialog.asksaveasfilename(
                defaultextension='.png',
                initialfile=img_name + '_polyglot.png',
                filetypes=[('PNG file', '*.png'), ('all', '*.*')],
                title='save polyglot as')
            if not out_path:
                log(c_log, '  cancelled', 'orange');
                return

            open(out_path, 'wb').write(result)
            log(c_log, f'  created: {Path(out_path).name}  ({fmt_bytes(len(result))})', 'green')
            log(c_log, f'  saved → {out_path}', 'muted')
            log(c_log, '\n  how to use:', 'accent')
            for tip in combo['tips']:
                log(c_log, f'    • {tip}', 'muted')
        except Exception as e:
            log(c_log, f'  error: {e}', 'red')

    threading.Thread(target=work, daemon=True).start()


# ─────────────────────────────────────────────
root.mainloop()
