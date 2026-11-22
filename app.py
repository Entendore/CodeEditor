import sys
import os
import sqlite3
import subprocess
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QPlainTextEdit, QWidget, QVBoxLayout, 
    QHBoxLayout, QFileDialog, QMessageBox, QTextEdit, QSplitter, 
    QDialog, QLineEdit, QPushButton, QLabel, QCompleter, QInputDialog,
    QComboBox, QListWidget, QDialogButtonBox, QFormLayout, QTextAreaEdit
)
from PySide6.QtCore import Qt, QRect, QSize, Signal, QSettings, QStringListModel
from PySide6.QtGui import (
    QFont, QColor, QSyntaxHighlighter, QTextCharFormat, 
    QRegularExpression, QPainter, QTextCursor, QAction, QTextFormat
)

# ==========================================
# ADVANCED RELATIONAL DATABASE HANDLER
# ==========================================
class SnippetDB:
    def __init__(self):
        self.db_path = os.path.join(os.getcwd(), "snippets.db")
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self.cursor.execute("PRAGMA foreign_keys = ON") # Enforce relational integrity
        self._migrate_schema()
        self._seed_defaults()

    def _migrate_schema(self):
        """Handles upgrading from the old single-table schema to the new relational one."""
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='snippet_triggers'")
        if not self.cursor.fetchone():
            # New schema doesn't exist, check if old one does
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='snippets'")
            old_table_exists = self.cursor.fetchone()
            
            if old_table_exists:
                print("Migrating database to new relational schema...")
                # Rename old table temporarily
                self.cursor.execute("ALTER TABLE snippets RENAME TO snippets_old")
            
            # Create new relational tables
            self._create_new_schema()
            
            if old_table_exists:
                # Migrate data from old table
                self.cursor.execute("SELECT language, title, trigger_word, code FROM snippets_old")
                old_data = self.cursor.fetchall()
                for lang, title, trigger, code in old_data:
                    if not trigger: trigger = title.lower().replace(" ", "_")
                    self.cursor.execute("INSERT OR IGNORE INTO languages (name) VALUES (?)", (lang.lower(),))
                    lang_id = self.cursor.execute("SELECT id FROM languages WHERE name=?", (lang.lower(),)).fetchone()[0]
                    self.cursor.execute("INSERT INTO snippets (language_id, title, code) VALUES (?, ?, ?)", (lang_id, title, code))
                    snip_id = self.cursor.execute("SELECT last_insert_rowid()").fetchone()[0]
                    self.cursor.execute("INSERT OR IGNORE INTO snippet_triggers (snippet_id, trigger_word) VALUES (?, ?)", (snip_id, trigger.lower()))
                self.cursor.execute("DROP TABLE snippets_old")
                self.conn.commit()
                print("Migration complete.")
        else:
            # Schema already exists, ensure foreign keys are on
            pass

    def _create_new_schema(self):
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS languages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snippets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                language_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (language_id) REFERENCES languages(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS snippet_triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snippet_id INTEGER NOT NULL,
                trigger_word TEXT UNIQUE NOT NULL,
                FOREIGN KEY (snippet_id) REFERENCES snippets(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS snippet_tags (
                snippet_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (snippet_id, tag_id),
                FOREIGN KEY (snippet_id) REFERENCES snippets(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );
        ''')
        self.conn.commit()

    def _seed_defaults(self):
        if self.cursor.execute("SELECT COUNT(*) FROM snippets").fetchone()[0] > 0: return
        
        self.cursor.executemany("INSERT OR IGNORE INTO languages (name) VALUES (?)", 
                                [("python",), ("javascript",), ("html",)])
        py_id = self.cursor.execute("SELECT id FROM languages WHERE name='python'").fetchone()[0]
        
        now = datetime.now().isoformat()
        defaults = [
            (py_id, "Function Definition", "Standard function", "def $0(self):\n    pass", now, now),
            (py_id, "Class Definition", "Standard class", "class $0:\n    def __init__(self):\n        pass", now, now),
            (py_id, "Main Guard", "Script entry point", "if __name__ == \"__main__\":\n    $0", now, now),
        ]
        self.cursor.executemany("INSERT INTO snippets (language_id, title, description, code, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", defaults)
        
        # Add multiple triggers for the first snippet (Function Def)
        func_id = self.cursor.execute("SELECT id FROM snippets WHERE title='Function Definition'").fetchone()[0]
        self.cursor.executemany("INSERT OR IGNORE INTO snippet_triggers (snippet_id, trigger_word) VALUES (?, ?)", 
                                [(func_id, "defn"), (func_id, "deffunc"), (func_id, "funcdef")])
        
        # Add triggers for others
        class_id = self.cursor.execute("SELECT id FROM snippets WHERE title='Class Definition'").fetchone()[0]
        main_id = self.cursor.execute("SELECT id FROM snippets WHERE title='Main Guard'").fetchone()[0]
        self.cursor.execute("INSERT OR IGNORE INTO snippet_triggers (snippet_id, trigger_word) VALUES (?, ?)", (class_id, "classn"))
        self.cursor.execute("INSERT OR IGNORE INTO snippet_triggers (snippet_id, trigger_word) VALUES (?, ?)", (main_id, "main"))
        
        # Add Tags
        self.cursor.executemany("INSERT OR IGNORE INTO tags (name) VALUES (?)", [("boilerplate",), ("oop",), ("structure",)])
        tag_boiler = self.cursor.execute("SELECT id FROM tags WHERE name='boilerplate'").fetchone()[0]
        tag_oop = self.cursor.execute("SELECT id FROM tags WHERE name='oop'").fetchone()[0]
        
        self.cursor.executemany("INSERT OR IGNORE INTO snippet_tags (snippet_id, tag_id) VALUES (?, ?)", 
                                [(func_id, tag_boiler), (class_id, tag_oop), (main_id, tag_boiler)])
        self.conn.commit()

    def add_snippet(self, language, title, description, triggers_list, tags_list, code):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO languages (name) VALUES (?)", (language.lower(),))
            lang_id = self.cursor.execute("SELECT id FROM languages WHERE name=?", (language.lower(),)).fetchone()[0]
            
            now = datetime.now().isoformat()
            self.cursor.execute("INSERT INTO snippets (language_id, title, description, code, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", 
                                (lang_id, title, description, code, now, now))
            snip_id = self.cursor.execute("SELECT last_insert_rowid()").fetchone()[0]
            
            for trigger in triggers_list:
                if trigger.strip():
                    self.cursor.execute("INSERT OR IGNORE INTO snippet_triggers (snippet_id, trigger_word) VALUES (?, ?)", 
                                        (snip_id, trigger.strip().lower()))
            
            for tag in tags_list:
                if tag.strip():
                    self.cursor.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag.strip().lower(),))
                    tag_id = self.cursor.execute("SELECT id FROM tags WHERE name=?", (tag.strip().lower(),)).fetchone()[0]
                    self.cursor.execute("INSERT OR IGNORE INTO snippet_tags (snippet_id, tag_id) VALUES (?, ?)", (snip_id, tag_id))
                    
            self.conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            QMessageBox.warning(None, "DB Error", f"Constraint failed: {str(e)}\nLikely a duplicate trigger word.")
            self.conn.rollback()
            return False

    def get_all_triggers(self):
        # Fast query for the autocomplete cache
        self.cursor.execute('''
            SELECT st.trigger_word, s.code 
            FROM snippet_triggers st 
            JOIN snippets s ON st.snippet_id = s.id
        ''')
        return {row[0].lower(): row[1] for row in self.cursor.fetchall()}

    def get_languages(self):
        self.cursor.execute("SELECT name FROM languages ORDER BY name")
        return [row[0].capitalize() for row in self.cursor.fetchall()]

    def get_tags_for_language(self, language):
        # Gets distinct tags that are actually used by a specific language
        self.cursor.execute('''
            SELECT DISTINCT t.name 
            FROM tags t
            JOIN snippet_tags st ON t.id = st.tag_id
            JOIN snippets s ON st.snippet_id = s.id
            JOIN languages l ON s.language_id = l.id
            WHERE l.name = ?
            ORDER BY t.name
        ''', (language.lower(),))
        return ["All Tags"] + [row[0].capitalize() for row in self.cursor.fetchall()]

    def get_snippets_filtered(self, language, tag="all tags"):
        query = '''
            SELECT s.id, s.title, s.description, GROUP_CONCAT(st.trigger_word, ', '), GROUP_CONCAT(t.name, ', ')
            FROM snippets s
            LEFT JOIN snippet_triggers st ON s.id = st.snippet_id
            LEFT JOIN snippet_tags stg ON s.id = stg.snippet_id
            LEFT JOIN tags t ON stg.tag_id = t.id
            JOIN languages l ON s.language_id = l.id
            WHERE l.name = ?
        '''
        params = [language.lower()]
        
        if tag.lower() != "all tags":
            query += " AND EXISTS (SELECT 1 FROM snippet_tags st2 JOIN tags t2 ON st2.tag_id=t2.id WHERE st2.snippet_id=s.id AND t2.name=?)"
            params.append(tag.lower())
            
        query += " GROUP BY s.id ORDER BY s.title"
        
        return self.cursor.execute(query, params).fetchall()

    def delete_snippet(self, snippet_id):
        # ON DELETE CASCADE handles deleting triggers and tags automatically
        self.cursor.execute("DELETE FROM snippets WHERE id=?", (snippet_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()


# ==========================================
# UI DIALOGS FOR SNIPPETS
# ==========================================
class AddSnippetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Snippet")
        self.setMinimumSize(500, 450)
        self.setStyleSheet("background-color: #2b2b2b; color: #d4d4d4;")

        layout = QFormLayout(self)
        style = "background-color: #1e1e1e; color: #d4d4d4; padding: 5px;"

        self.lang_input = QComboBox(); self.lang_input.setEditable(True)
        self.lang_input.addItems(["Python", "C++", "JavaScript", "Java", "HTML", "CSS"])
        self.lang_input.setStyleSheet(style)
        layout.addRow("Language:", self.lang_input)

        self.title_input = QLineEdit(); self.title_input.setStyleSheet(style)
        layout.addRow("Title:", self.title_input)

        self.desc_input = QLineEdit(); self.desc_input.setStyleSheet(style)
        self.desc_input.setPlaceholderText("Short description of what it does")
        layout.addRow("Description:", self.desc_input)

        self.trigger_input = QLineEdit(); self.trigger_input.setStyleSheet(style)
        self.trigger_input.setPlaceholderText("Comma separated (e.g., defn, func, deff)")
        layout.addRow("Trigger Words:", self.trigger_input)

        self.tag_input = QLineEdit(); self.tag_input.setStyleSheet(style)
        self.tag_input.setPlaceholderText("Comma separated (e.g., oop, boilerplate, django)")
        layout.addRow("Tags:", self.tag_input)

        self.code_input = QPlainTextEdit(); self.code_input.setFont(QFont("Consolas", 10))
        self.code_input.setPlaceholderText("Code here. Use $0 for final cursor position.")
        self.code_input.setStyleSheet(style)
        layout.addRow("Code:", self.code_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addRow(buttons)


class SnippetManagerDialog(QDialog):
    def __init__(self, db, editor, parent=None):
        super().__init__(parent)
        self.db = db; self.editor = editor
        self.setWindowTitle("Snippet Manager (Relational DB)")
        self.resize(550, 500)
        self.setStyleSheet("background-color: #2b2b2b; color: #d4d4d4;")

        layout = QVBoxLayout(self)
        style = "background-color: #1e1e1e; color: #d4d4d4; padding: 5px;"

        # Filters
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Lang:"))
        self.lang_filter = QComboBox(); self.lang_filter.setStyleSheet(style)
        filter_layout.addWidget(self.lang_filter)
        
        filter_layout.addWidget(QLabel("Tag:"))
        self.tag_filter = QComboBox(); self.tag_filter.setStyleSheet(style)
        filter_layout.addWidget(self.tag_filter)

        btn_add = QPushButton("➕ Add"); btn_add.clicked.connect(self.open_add_dialog); btn_add.setStyleSheet("padding: 5px;")
        filter_layout.addWidget(btn_add)
        layout.addLayout(filter_layout)

        self.snippet_list = QListWidget()
        self.snippet_list.setStyleSheet("QListWidget { background-color: #1e1e1e; color: #d4d4d4; border: none; padding: 5px; } QListWidget::item:selected { background-color: #264f78; }")
        layout.addWidget(self.snippet_list)

        # Details Preview
        self.details_label = QLabel("Select a snippet to see details.")
        self.details_label.setWordWrap(True)
        self.details_label.setStyleSheet("color: #858585; padding: 10px; background-color: #252526; border: 1px solid #333;")
        layout.addWidget(self.details_label)

        action_layout = QHBoxLayout()
        btn_load = QPushButton("⬇ Load"); btn_load.clicked.connect(self.load_snippet)
        btn_load.setStyleSheet("padding: 8px; background-color: #0078d4; color: white; font-weight: bold;")
        btn_delete = QPushButton("🗑 Delete"); btn_delete.clicked.connect(self.delete_snippet)
        btn_delete.setStyleSheet("padding: 8px; background-color: #d13438; color: white;")
        btn_close = QPushButton("Close"); btn_close.clicked.connect(self.close); btn_close.setStyleSheet("padding: 8px;")
        
        action_layout.addWidget(btn_load); action_layout.addWidget(btn_delete)
        action_layout.addStretch(); action_layout.addWidget(btn_close)
        layout.addLayout(action_layout)

        self.refresh_languages()
        self.lang_filter.currentTextChanged.connect(self.refresh_tags)
        self.lang_filter.currentTextChanged.connect(self.refresh_snippets)
        self.tag_filter.currentTextChanged.connect(self.refresh_snippets)
        self.snippet_list.itemClicked.connect(self.show_details)

    def refresh_languages(self):
        self.lang_filter.blockSignals(True); self.lang_filter.clear()
        self.lang_filter.addItems(self.db.get_languages())
        self.lang_filter.blockSignals(False)
        if self.lang_filter.count() > 0:
            self.refresh_tags(self.lang_filter.currentText())
            self.refresh_snippets(self.lang_filter.currentText())

    def refresh_tags(self, language):
        self.tag_filter.blockSignals(True); self.tag_filter.clear()
        self.tag_filter.addItems(self.db.get_tags_for_language(language))
        self.tag_filter.blockSignals(False)

    def refresh_snippets(self, language):
        self.snippet_list.clear(); self.details_label.setText("Select a snippet to see details.")
        if not language: return
        tag = self.tag_filter.currentText()
        for snip_id, title, desc, triggers, tags in self.db.get_snippets_filtered(language, tag):
            display = f"{title}  [{triggers if triggers else 'No Trigger'}]  ({tags if tags else 'No Tags'})"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, snip_id) # Store ID hidden in UI
            self.snippet_list.addItem(item)

    def show_details(self, item):
        snip_id = item.data(Qt.ItemDataRole.UserRole)
        # Fetch full details for preview
        row = self.db.cursor.execute("SELECT description, code, created_at FROM snippets WHERE id=?", (snip_id,)).fetchone()
        if row:
            desc, code, created = row
            self.details_label.setText(f"<b>Description:</b> {desc or 'None'}<br><b>Created:</b> {created[:10]}<br><br><pre>{code[:200]}...</pre>")

    def open_add_dialog(self):
        dialog = AddSnippetDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            lang = dialog.lang_input.currentText()
            title = dialog.title_input.text()
            desc = dialog.desc_input.text()
            triggers = [t.strip() for t in dialog.trigger_input.text().split(',') if t.strip()]
            tags = [t.strip() for t in dialog.tag_input.text().split(',') if t.strip()]
            code = dialog.code_input.toPlainText()
            
            if lang and title and code and triggers:
                if self.db.add_snippet(lang, title, desc, triggers, tags, code):
                    self.refresh_languages()
                    self.lang_filter.setCurrentText(lang.capitalize())
                else:
                    QMessageBox.warning(self, "Error", "Failed to add. Check for duplicate trigger words.")
            else:
                QMessageBox.warning(self, "Error", "Language, Title, at least one Trigger, and Code are required.")

    def load_snippet(self):
        item = self.snippet_list.currentItem()
        if not item: return
        snip_id = item.data(Qt.ItemDataRole.UserRole)
        code = self.db.cursor.execute("SELECT code FROM snippets WHERE id=?", (snip_id,)).fetchone()[0]
        self.editor.insert_snippet_text(code)
        self.close()

    def delete_snippet(self):
        item = self.snippet_list.currentItem()
        if not item: return
        snip_id = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, "Delete", "Delete this snippet and all its triggers/tags?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_snippet(snip_id)
            self.refresh_tags(self.lang_filter.currentText())
            self.refresh_snippets(self.lang_filter.currentText())

    def closeEvent(self, event):
        self.editor.refresh_snippet_cache()
        super().closeEvent(event)


# ==========================================
# EDITOR WIDGETS (LineNumber, CodeEditor, etc.)
# ==========================================
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#2b2b2b"))
        block = self.editor.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top()
        bottom = top + self.editor.blockBoundingRect(block).height()
        highlight_color, default_color = QColor("#ffffff"), QColor("#858585")

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if (block_number + 1) in self.editor.bookmarks:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#0078d4"))
                    painter.drawEllipse(6, int(top) + 4, 10, 10)
                number = str(block_number + 1)
                is_current = block_number == self.editor.textCursor().blockNumber()
                painter.setPen(highlight_color if is_current else default_color)
                font = painter.font(); font.setBold(is_current); painter.setFont(font)
                painter.drawText(20, int(top), self.width() - 20, self.editor.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + self.editor.blockBoundingRect(block).height()
            block_number += 1

    def mousePressEvent(self, event):
        if event.position().x() < 20:
            block = self.editor.firstVisibleBlock()
            top = self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top()
            bottom = top + self.editor.blockBoundingRect(block).height()
            while block.isValid():
                if top <= event.position().y() <= bottom:
                    line_num = block.blockNumber() + 1
                    self.editor.bookmarks.add(line_num) if line_num not in self.editor.bookmarks else self.editor.bookmarks.remove(line_num)
                    self.update(); break
                block = block.next(); top = bottom; bottom = top + self.editor.blockBoundingRect(block).height()


class CodeEditor(QPlainTextEdit):
    status_message = Signal(str)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.line_number_area = LineNumberArea(self)
        self.bookmarks = set()
        self.snippet_triggers = {} # Cache: {trigger: code}

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.cursorPositionChanged.connect(self.update_cursor_position)

        self.update_line_number_area_width(0)
        self.highlight_current_line()

        font = QFont("Consolas", 11); font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.setStyleSheet("QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4; border: none; padding-left: 10px; }")

        self.completer = QCompleter(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setWidget(self)
        self.completer.activated.connect(self.insert_completion)
        
        self.python_keywords = ["def", "class", "import", "from", "if", "else", "elif", "return", "for", "while", 
                                "try", "except", "finally", "with", "as", "pass", "break", "continue", "in", "not", 
                                "and", "or", "is", "None", "True", "False", "lambda", "yield", "global", "nonlocal", "assert"]
        self.python_builtins = ["print", "range", "len", "int", "str", "float", "list", "dict", "set", "tuple", 
                                "type", "isinstance", "input", "open", "super", "__init__", "__name__", "self",
                                "enumerate", "zip", "map", "filter", "sorted", "reversed", "abs", "max", "min", "sum"]
        self.refresh_snippet_cache()

    def refresh_snippet_cache(self):
        self.snippet_triggers = self.db.get_all_triggers()
        combined_list = self.python_keywords + self.python_builtins + list(self.snippet_triggers.keys())
        self.completer.setModel(QStringListModel(combined_list))

    def insert_completion(self, completion):
        tc = self.textCursor()
        tc.movePosition(tc.MoveOperation.Left, tc.KeepAnchor, len(self.completer.completionPrefix()))
        if completion.lower() in self.snippet_triggers:
            self.insert_snippet_text(self.snippet_triggers[completion.lower()], tc)
        else:
            tc.insertText(completion)
            self.setTextCursor(tc)

    def insert_snippet_text(self, code, cursor=None):
        if not cursor: cursor = self.textCursor()
        cursor.removeSelectedText()
        if "$0" in code:
            parts = code.split("$0", 1)
            cursor.insertText(parts[0])
            cursor_pos = cursor.position()
            cursor.insertText(parts[1])
            cursor.setPosition(cursor_pos)
        else:
            cursor.insertText(code)
        self.setTextCursor(cursor); self.setFocus()

    def text_under_cursor(self):
        tc = self.textCursor(); tc.select(QTextCursor.SelectionType.WordUnderCursor); return tc.selectedText()

    def keyPressEvent(self, event):
        key = event.key(); text = event.text()
        if self.completer.popup().isVisible():
            if key in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab): self.completer.popup().hide(); return
            elif key == Qt.Key_Escape: self.completer.popup().hide(); super().keyPressEvent(event); return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor(); line_text = cursor.block().text()
            current_indent = len(line_text) - len(line_text.lstrip())
            if line_text.rstrip().endswith(':'): current_indent += 4
            super().keyPressEvent(event); self.insertPlainText(' ' * current_indent); self.trigger_completer(); return

        brackets = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}
        if text in brackets:
            cursor = self.textCursor()
            if cursor.hasSelection():
                selected_text = cursor.selectedText(); super().keyPressEvent(event)
                self.insertPlainText(selected_text + brackets[text])
                cursor = self.textCursor(); cursor.movePosition(cursor.MoveLeft, cursor.KeepAnchor, len(selected_text) + 1)
                self.setTextCursor(cursor); return
            else:
                super().keyPressEvent(event); self.insertPlainText(brackets[text])
                cursor = self.textCursor(); cursor.movePosition(cursor.MoveLeft); self.setTextCursor(cursor); return

        if key == Qt.Key_Backspace:
            cursor = self.textCursor()
            if not cursor.hasSelection() and cursor.position() > 0:
                cursor.movePosition(cursor.MoveLeft, cursor.KeepAnchor); char_before = cursor.selectedText()
                cursor.movePosition(cursor.MoveRight); cursor.movePosition(cursor.MoveRight, cursor.KeepAnchor); char_after = cursor.selectedText()
                if char_before in ['(', '[', '{', '"', "'"] and char_before == char_after:
                    cursor.deleteChar(); cursor.movePosition(cursor.MoveLeft); cursor.deleteChar(); return

        super().keyPressEvent(event)
        if text.isalnum() or text == '_': self.trigger_completer()
        else: self.completer.popup().hide()

    def trigger_completer(self):
        word = self.text_under_cursor()
        if len(word) >= 2:
            self.completer.setCompletionPrefix(word); popup = self.completer.popup()
            popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
            cursor_rect = self.cursorRect()
            cursor_rect.setWidth(self.completer.popup().sizeHintForColumn(0) + self.completer.popup().verticalScrollBar().sizeHint().width())
            self.completer.complete(cursor_rect)
        else: self.completer.popup().hide()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y(); font = self.font()
            font.setPointSize(max(1, font.pointSize() + (1 if delta > 0 else -1))); self.setFont(font)
        else: super().wheelEvent(event)

    def update_cursor_position(self):
        c = self.textCursor(); self.status_message.emit(f"Ln {c.blockNumber() + 1}, Col {c.columnNumber() + 1}")

    def line_number_area_width(self):
        digits = 1; max_value = max(1, self.blockCount())
        while max_value >= 10: max_value /= 10; digits += 1
        return 30 + self.fontMetrics().horizontalAdvance('9') * digits

    def update_line_number_area_width(self, n): self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
    def update_line_number_area(self, rect, dy):
        if dy: self.line_number_area.scroll(0, dy)
        else: self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()): self.update_line_number_area_width(0)
    def resizeEvent(self, event):
        super().resizeEvent(event); cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area.width(), cr.height()))
    def highlight_current_line(self):
        extra_selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection(); selection.format.setBackground(QColor("#2a2d2e"))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor(); selection.cursor.clearSelection(); extra_selections.append(selection)
        self.setExtraSelections(extra_selections)


class PythonSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document); self.highlighting_rules = []
        kw_fmt = QTextCharFormat(); kw_fmt.setForeground(QColor("#c586c0")); kw_fmt.setFontWeight(QFont.Weight.Bold)
        for w in ["def", "class", "import", "from", "if", "else", "elif", "return", "for", "while", "try", "except", "finally", "with", "as", "pass", "break", "continue", "in", "not", "and", "or", "is", "None", "True", "False", "lambda", "yield"]:
            self.highlighting_rules.append((QRegularExpression(r"\b" + w + r"\b"), kw_fmt))
        str_fmt = QTextCharFormat(); str_fmt.setForeground(QColor("#ce9178"))
        self.highlighting_rules.append((QRegularExpression(r'\".*\"|\'.*\''), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r'\"\"\"[\s\S]*?\"\"\"'), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r"'''[\s\S]*?'''"), str_fmt))
        com_fmt = QTextCharFormat(); com_fmt.setForeground(QColor("#6a9955")); com_fmt.setFontItalic(True)
        self.highlighting_rules.append((QRegularExpression(r"#.*"), com_fmt))
        func_fmt = QTextCharFormat(); func_fmt.setForeground(QColor("#dcdcaa"))
        self.highlighting_rules.append((QRegularExpression(r"\b(?<=def\s)[a-zA-Z_][a-zA-Z0-9_]*"), func_fmt))
        self_fmt = QTextCharFormat(); self_fmt.setForeground(QColor("#569cd6"))
        self.highlighting_rules.append((QRegularExpression(r"\bself\b"), self_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            it = pattern.globalMatch(text)
            while it.hasNext(): m = it.next(); self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class FindReplaceDialog(QDialog):
    def __init__(self, editor, parent=None):
        super().__init__(parent); self.editor = editor; self.setWindowTitle("Find & Replace"); self.setFixedSize(400, 150); self.setStyleSheet("background-color: #2b2b2b; color: #d4d4d4;")
        layout = QVBoxLayout(self)
        fl = QHBoxLayout(); fl.addWidget(QLabel("Find:")); self.fi = QLineEdit(); self.fi.returnPressed.connect(self.fn); fl.addWidget(self.fi); b = QPushButton("Find"); b.clicked.connect(self.fn); fl.addWidget(b); layout.addLayout(fl)
        rl = QHBoxLayout(); rl.addWidget(QLabel("Replace:")); self.ri = QLineEdit(); rl.addWidget(self.ri); b2 = QPushButton("Replace"); b2.clicked.connect(self.rc); rl.addWidget(b2); layout.addLayout(rl)
        b3 = QPushButton("Replace All"); b3.clicked.connect(self.ra); layout.addWidget(b3)
    def fn(self):
        t=self.fi.text()
        if not t:return
        if not self.editor.find(t): c=self.editor.textCursor(); c.movePosition(c.Start); self.editor.setTextCursor(c); self.editor.find(t)
    def rc(self):
        if self.editor.textCursor().selectedText()==self.fi.text(): self.editor.insertPlainText(self.ri.text())
        self.fn()
    def ra(self): self.editor.setPlainText(self.editor.toPlainText().replace(self.fi.text(), self.ri.text()))


# ==========================================
# MAIN WINDOW
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Professional Code Editor (Relational Snippets)")
        self.resize(1000, 700)
        self.settings = QSettings("MyCompany", "PyCodeEditor")
        self.snippet_db = SnippetDB()

        self.editor = CodeEditor(self.snippet_db)
        self.highlighter = PythonSyntaxHighlighter(self.editor.document())
        self.editor.status_message.connect(self.statusBar().showMessage)
        
        self.console = QTextEdit(); self.console.setReadOnly(True); self.console.setFont(QFont("Consolas", 10))
        self.console.setStyleSheet("QTextEdit { background-color: #1a1a1a; color: #d4d4d4; border-top: 1px solid #444; padding: 5px; }")
        self.console.setPlaceholderText("Output will appear here...")

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.editor); self.splitter.addWidget(self.console); self.splitter.setSizes([600, 200])
        self.setCentralWidget(self.splitter)

        self.create_menus(); self.create_toolbar()
        self.statusBar().showMessage("Ln 1, Col 1")
        self.current_file = None; self.find_dialog = None
        self.load_settings()

    def create_toolbar(self):
        toolbar = self.addToolBar("Main"); toolbar.setMovable(False); toolbar.setStyleSheet("background-color: #2b2b2b; border: none; spacing: 5px;")
        toolbar.addAction("▶ Run", self.run_code, "Ctrl+R"); toolbar.addAction("🔍 Find", self.open_find_replace, "Ctrl+H")
        toolbar.addAction("📂 Snippets", self.open_snippet_manager, "Ctrl+Shift+X")

    def create_menus(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        file_menu.addAction("Open", self.open_file, "Ctrl+O"); file_menu.addAction("Save", self.save_file, "Ctrl+S")
        file_menu.addAction("Save As...", self.save_file_as, "Ctrl+Shift+S"); file_menu.addSeparator(); file_menu.addAction("Exit", self.close, "Ctrl+Q")
        edit_menu = menubar.addMenu("Edit")
        edit_menu.addAction("Undo", self.editor.undo, "Ctrl+Z"); edit_menu.addAction("Redo", self.editor.redo, "Ctrl+Y"); edit_menu.addSeparator()
        edit_menu.addAction("Find & Replace", self.open_find_replace, "Ctrl+H")
        snippet_menu = menubar.addMenu("Snippets")
        snippet_menu.addAction("Manage Snippets", self.open_snippet_manager, "Ctrl+Shift+X")

    def open_snippet_manager(self):
        SnippetManagerDialog(self.snippet_db, self.editor, self).exec()

    def closeEvent(self, event):
        self.save_settings(); self.snippet_db.close(); super().closeEvent(event)

    def save_settings(self):
        self.settings.setValue("geometry", self.saveGeometry()); self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("splitter_state", self.splitter.saveState()); self.settings.setValue("font_size", self.editor.font().pointSize())
        if self.current_file: self.settings.setValue("last_file", self.current_file)
        else: self.settings.remove("last_file")

    def load_settings(self):
        if self.settings.value("geometry"): self.restoreGeometry(self.settings.value("geometry"))
        if self.settings.value("window_state"): self.restoreState(self.settings.value("window_state"))
        if self.settings.value("splitter_state"): self.splitter.restoreState(self.settings.value("splitter_state"))
        font_size = self.settings.value("font_size", type=int)
        if font_size: self.editor.font().setPointSize(font_size); self.editor.setFont(self.editor.font())
        last_file = self.settings.value("last_file", type=str)
        if last_file and os.path.exists(last_file):
            try:
                with open(last_file, 'r', encoding='utf-8') as f: self.editor.setPlainText(f.read())
                self.current_file = last_file; self.setWindowTitle(f"Professional Code Editor - {last_file}")
            except: pass

    def run_code(self):
        if not self.current_file:
            QMessageBox.warning(self, "No File", "Save the file before running."); self.save_file_as()
            if not self.current_file: return
        self.save_file(); self.console.clear(); self.console.append(f"--- Running {self.current_file} ---\n")
        try:
            result = subprocess.run(['python', self.current_file], capture_output=True, text=True, timeout=10)
            if result.stdout: self.console.append(result.stdout)
            if result.stderr: self.console.append(f"<span style='color: #f48771;'>{result.stderr}</span>")
            self.console.append("\n--- Process Finished ---")
        except Exception as e: self.console.append(f"<span style='color: #f48771;'>{str(e)}</span>")
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def open_file(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Open File", "", "Python Files (*.py);;All Files (*)")
        if fp:
            try:
                with open(fp, 'r', encoding='utf-8') as f: self.editor.setPlainText(f.read())
                self.current_file = fp; self.setWindowTitle(f"Professional Code Editor - {fp}")
            except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def save_file(self):
        if not self.current_file: self.save_file_as(); return
        try:
            with open(self.current_file, 'w', encoding='utf-8') as f: f.write(self.editor.toPlainText())
            self.statusBar().showMessage(f"Saved: {self.current_file}")
        except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def save_file_as(self):
        fp, _ = QFileDialog.getSaveFileName(self, "Save File", "", "Python Files (*.py);;All Files (*)")
        if fp: self.current_file = fp; self.save_file(); self.setWindowTitle(f"Professional Code Editor - {fp}")
        
    def open_find_replace(self):
        if not self.find_dialog: self.find_dialog = FindReplaceDialog(self.editor, self)
        self.find_dialog.show(); self.find_dialog.raise_(); self.find_dialog.activateWindow()


if __name__ == "__main__":
    app = QApplication(sys.argv); app.setStyle("Fusion")
    p = app.palette()
    for role, color in [(p.ColorRole.Window, "#2b2b2b"), (p.ColorRole.WindowText, "#d4d4d4"), (p.ColorRole.Base, "#1e1e1e"), (p.ColorRole.Text, "#d4d4d4"), (p.ColorRole.Button, "#2b2b2b"), (p.ColorRole.ButtonText, "#d4d4d4"), (p.ColorRole.Highlight, "#264f78"), (p.ColorRole.HighlightedText, "#d4d4d4")]:
        p.setColor(role, QColor(color))
    app.setPalette(p)
    window = MainWindow(); window.show(); sys.exit(app.exec())