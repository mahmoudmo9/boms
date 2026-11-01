import json, sqlite3
from suite.storage import move_tree, rebase_paths, check_writable


def test_move_and_rebase(tmp_path):
    old, new = tmp_path / 'old', tmp_path / 'new'
    (old / '1405071200001').mkdir(parents=True); (old / '1405071200001' / 'a.pdf').write_text('x')
    (new / '1405071200001').mkdir(parents=True); (new / '1405071200001' / 'b.pdf').write_text('y')
    (old / 'dup.txt').write_text('1'); (new / 'dup.txt').write_text('2')
    moved, problems = move_tree(old, new)
    assert (new / '1405071200001' / 'a.pdf').exists() and (new / '1405071200001' / 'b.pdf').exists()
    assert moved == 1 and len(problems) == 1 and (new / 'dup.txt').read_text() == '2'
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE files (local_path TEXT, n INTEGER)'); con.execute('CREATE TABLE cases (data TEXT)')
    con.execute('INSERT INTO files VALUES (?,1)', (str(old / '1405071200001' / 'a.pdf'),))
    con.execute('INSERT INTO cases VALUES (?)', (json.dumps({'docx': str(old / 'x.docx')}),))
    assert rebase_paths(con, old, new) >= 2
    assert con.execute('SELECT local_path FROM files').fetchone()[0] == str(new / '1405071200001' / 'a.pdf')
    assert json.loads(con.execute('SELECT data FROM cases').fetchone()[0])['docx'] == str(new / 'x.docx')
    assert check_writable(new)[0]
