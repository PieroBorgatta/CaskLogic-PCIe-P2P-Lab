import re
from pathlib import Path

def apply_text(text, patch, wanted, reverse=False):
    lines=patch.splitlines(keepends=True); original=text.splitlines(keepends=True)
    active=False; output=[]; cursor=0; changes=0; i=0
    while i<len(lines):
        line=lines[i]
        if line.startswith('--- '):
            old=line[4:].split()[0]; new=lines[i+1][4:].split()[0]
            active=(old.removeprefix('a/')==wanted and new.removeprefix('b/')==wanted)
            i+=2; continue
        if active and line.startswith('@@ '):
            m=re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@',line)
            assert m,line
            position=max(0,int(m[3] if reverse else m[1])-1)
            before=[];after=[];i+=1
            while i<len(lines) and not lines[i].startswith(('@@ ','--- ')):
                h=lines[i]
                if h.startswith(' '):before.append(h[1:]);after.append(h[1:])
                elif h.startswith('-'):before.append(h[1:])
                elif h.startswith('+'):after.append(h[1:])
                elif h.startswith('\\'):pass
                else:break
                i+=1
            if reverse:before,after=after,before
            assert position>=cursor,('overlap',wanted,position,cursor)
            assert original[position:position+len(before)]==before,('context mismatch',wanted,position)
            output.extend(original[cursor:position]);output.extend(after);cursor=position+len(before);changes+=1
            continue
        i+=1
    assert changes,('no hunks',wanted)
    output.extend(original[cursor:]);return ''.join(output)

def apply_file(root, patch_path, wanted):
    path=Path(root)/wanted
    path.write_text(apply_text(path.read_text(),Path(patch_path).read_text(),wanted))
