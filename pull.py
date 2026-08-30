#!/usr/bin/env python3
"""
info-to-text -- convert item SNBT (from the InfoCopy mod) into legacy '&' color codes.

Just run it:  python info_to_text.py
It reads the item data from your clipboard, then asks whether you want the
lore, the name, or both.
"""

import re
import subprocess
import sys

# Make sure we can print non-Latin text (Cyrillic, etc.) on the Windows console.
for _stream in (sys.stdout, sys.stdin):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ---------- Named color table ----------
NAMED = {
    "black": "0", "dark_blue": "1", "dark_green": "2", "dark_aqua": "3",
    "dark_red": "4", "dark_purple": "5", "gold": "6", "gray": "7",
    "dark_gray": "8", "blue": "9", "green": "a", "aqua": "b",
    "red": "c", "light_purple": "d", "yellow": "e", "white": "f",
}

FMT_KEYS = ("bold", "italic", "underlined", "strikethrough", "obfuscated")
FMT_CODE = {"bold": "l", "italic": "o", "underlined": "n",
            "strikethrough": "m", "obfuscated": "k"}


# ---------- Tolerant SNBT parser ----------
class SNBTParser:
    def __init__(self, text):
        self.s = text
        self.i = 0

    def fail(self, msg):
        raise ValueError(f"{msg} at position {self.i}")

    def ws(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def parse(self):
        return self.value()

    def value(self):
        self.ws()
        c = self.s[self.i] if self.i < len(self.s) else ""
        if c == "{":
            return self.compound()
        if c == "[":
            return self.list()
        if c in ('"', "'"):
            return self.quoted()
        return self.unquoted()

    def quoted(self):
        q = self.s[self.i]
        self.i += 1
        out = []
        while self.i < len(self.s):
            c = self.s[self.i]
            self.i += 1
            if c == "\\":
                out.append(self.s[self.i])
                self.i += 1
                continue
            if c == q:
                return "".join(out)
            out.append(c)
        self.fail("unterminated string")

    def key(self):
        self.ws()
        if self.s[self.i] in ('"', "'"):
            return self.quoted()
        start = self.i
        while self.i < len(self.s) and re.match(r"[A-Za-z0-9_\-.+]", self.s[self.i]):
            self.i += 1
        if self.i == start:
            self.fail("expected key")
        return self.s[start:self.i]

    def compound(self):
        self.i += 1
        obj = {}
        self.ws()
        if self.s[self.i] == "}":
            self.i += 1
            return obj
        while True:
            self.ws()
            k = self.key()
            self.ws()
            if self.s[self.i] != ":":
                self.fail("expected ':'")
            self.i += 1
            obj[k] = self.value()
            self.ws()
            if self.s[self.i] == ",":
                self.i += 1
                continue
            if self.s[self.i] == "}":
                self.i += 1
                break
            self.fail("expected ',' or '}'")
        return obj

    def list(self):
        self.i += 1
        self.ws()
        # typed-array prefix like  I;  B;  L;
        if (self.i + 1 < len(self.s) and self.s[self.i].isalpha()
                and self.s[self.i + 1] == ";"):
            self.i += 2
        arr = []
        self.ws()
        if self.s[self.i] == "]":
            self.i += 1
            return arr
        while True:
            arr.append(self.value())
            self.ws()
            if self.s[self.i] == ",":
                self.i += 1
                self.ws()
                continue
            if self.s[self.i] == "]":
                self.i += 1
                break
            self.fail("expected ',' or ']'")
        return arr

    def unquoted(self):
        start = self.i
        while (self.i < len(self.s) and self.s[self.i] not in ",{}[]:"
               and not self.s[self.i].isspace()):
            self.i += 1
        tok = self.s[start:self.i]
        if tok == "":
            self.fail("unexpected character")
        if tok == "true":
            return True
        if tok == "false":
            return False
        m = re.fullmatch(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?([bBsSlLfFdD]?)", tok)
        if m:
            num = float(tok[:len(tok) - len(m.group(1))] if m.group(1) else tok)
            return int(num) if num == int(num) else num
        return tok


def parse_snbt(text):
    return SNBTParser(text).parse()


# ---------- Text component -> '&' codes ----------
def truthy(v):
    return v is True or v == 1 or v == "1" or v == "true"


def flatten(node, inherited, out):
    if node is None:
        return
    if isinstance(node, (str, int, float)):
        piece = dict(inherited)
        piece["text"] = str(node)
        out.append(piece)
        return
    if isinstance(node, list):
        parent_style = inherited
        for idx, child in enumerate(node):
            if idx == 0:
                before = len(out)
                flatten(child, inherited, out)
                parent_style = out[-1].get("__style", inherited) if len(out) > before else inherited
            else:
                flatten(child, parent_style, out)
        return
    # dict component
    style = dict(inherited)
    if "color" in node:
        style["color"] = node["color"]
    for k in FMT_KEYS:
        if k in node:
            style[k] = truthy(node[k])
    piece = dict(style)
    piece["text"] = str(node["text"]) if "text" in node else ""
    piece["__style"] = style
    out.append(piece)
    if isinstance(node.get("extra"), list):
        for child in node["extra"]:
            flatten(child, style, out)


def color_to_code(color):
    if not color:
        return ""
    if color[0] == "#":
        h = color[1:].lower()
        if len(h) == 6:
            return "&#" + h
        return ""
    return ("&" + NAMED[color]) if color in NAMED else ""


def legacy_for(p):
    pre = color_to_code(p.get("color"))
    for k in FMT_KEYS:
        if p.get(k):
            pre += "&" + FMT_CODE[k]
    return pre


def component_to_codes(node):
    pieces = []
    flatten(node, {}, pieces)
    return "".join(legacy_for(p) + p["text"] for p in pieces)


# ---------- IO ----------
def read_clipboard():
    # Force PowerShell to emit UTF-8 so non-Latin text (Cyrillic, etc.) survives.
    cmd = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
           "Get-Clipboard -Raw")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, timeout=10, stdin=subprocess.DEVNULL,
        )
        return out.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""


def get_text(comp, *keys):
    for k in keys:
        if k in comp:
            return comp[k]
    return None


def print_lore(lore):
    if isinstance(lore, list):
        for line in lore:
            print(component_to_codes(line))
    else:
        print(component_to_codes(lore))


def main():
    raw = read_clipboard().strip()
    if not raw:
        raw = input("Clipboard was empty. Paste the item SNBT here:\n").strip()
    if not raw:
        print("No input given.")
        return

    try:
        data = parse_snbt(raw)
    except ValueError as e:
        print("Parse error:", e)
        return

    comp = data["components"] if isinstance(data, dict) and "components" in data else data
    name_node = get_text(comp, "minecraft:custom_name", "custom_name",
                         "minecraft:item_name", "item_name")
    lore_node = get_text(comp, "minecraft:lore", "lore")

    print()
    print("What do you want the '&' color codes for?")
    print("  1 = lore")
    print("  2 = name")
    print("  3 = both")
    raw_choice = input("Choice [1/2/3]: ")
    digits = "".join(c for c in raw_choice if c.isdigit())
    choice = digits[:1]

    print()
    if choice in ("1", "3"):
        print("--- LORE ---")
        if lore_node is None:
            print("(this item has no lore)")
        else:
            print_lore(lore_node)
        if choice == "3":
            print()

    if choice in ("2", "3"):
        print("--- NAME ---")
        if name_node is None:
            print("(this item has no custom/item name)")
        else:
            print(component_to_codes(name_node))

    if choice not in ("1", "2", "3"):
        print("Unknown choice; expected 1, 2, or 3.")


if __name__ == "__main__":
    main()
