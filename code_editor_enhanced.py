import sys
import os
import re
import json
import sqlite3
import subprocess
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QPlainTextEdit, QWidget, QVBoxLayout,
    QHBoxLayout, QFileDialog, QMessageBox, QTextEdit, QSplitter,
    QDialog, QLineEdit, QPushButton, QLabel, QCompleter, QInputDialog,
    QComboBox, QListWidget, QDialogButtonBox, QFormLayout,
    QTabWidget, QDockWidget, QTreeView, QFileSystemModel,
    QSpinBox, QSizePolicy, QHeaderView, QAbstractItemView
)
from PySide6.QtCore import (
    Qt, QRect, QSize, Signal, QSettings, QStringListModel,
    QTimer, QDir, QFileInfo, QPoint, QRegularExpression
)
from PySide6.QtGui import (
    QFont, QColor, QSyntaxHighlighter, QTextCharFormat,
    QPainter, QTextCursor, QAction, QTextFormat,
    QPainterPath, QPen, QBrush, QTextDocument, QPixmap
)


# ============================================================
#  ADVANCED RELATIONAL DATABASE HANDLER (enhanced)
# ============================================================
class SnippetDB:
    def __init__(self):
        # Use a stable location next to the script, falling back to home dir
        _base = os.path.dirname(os.path.abspath(__file__))
        if not os.access(_base, os.W_OK):
            _base = os.path.expanduser("~")
        self.db_path = os.path.join(_base, "snippets.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("PRAGMA foreign_keys = ON")
        self.cursor.execute("PRAGMA journal_mode = WAL")      # faster concurrent reads
        self.cursor.execute("PRAGMA synchronous = NORMAL")    # safe but faster than FULL
        self.cursor.execute("PRAGMA cache_size = -8000")       # 8 MB page cache
        self._migrate_schema()
        self._seed_defaults()

    # ---------- schema ----------
    def _migrate_schema(self):
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='snippet_triggers'")
        if not self.cursor.fetchone():
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='snippets'")
            old_table_exists = self.cursor.fetchone()
            if old_table_exists:
                print("Migrating database to new relational schema...")
                self.cursor.execute("ALTER TABLE snippets RENAME TO snippets_old")
            self._create_new_schema()
            if old_table_exists:
                self.cursor.execute("SELECT language, title, trigger_word, code FROM snippets_old")
                old_data = self.cursor.fetchall()
                for lang, title, trigger, code in old_data:
                    if not trigger:
                        trigger = title.lower().replace(" ", "_")
                    self.cursor.execute("INSERT OR IGNORE INTO languages (name) VALUES (?)", (lang.lower(),))
                    lang_id = self.cursor.execute("SELECT id FROM languages WHERE name=?", (lang.lower(),)).fetchone()[0]
                    self.cursor.execute("INSERT INTO snippets (language_id, title, code) VALUES (?, ?, ?)", (lang_id, title, code))
                    snip_id = self.cursor.execute("SELECT last_insert_rowid()").fetchone()[0]
                    self.cursor.execute("INSERT OR IGNORE INTO snippet_triggers (snippet_id, trigger_word) VALUES (?, ?)",
                                        (snip_id, trigger.lower()))
                self.cursor.execute("DROP TABLE snippets_old")
                self.conn.commit()
                print("Migration complete.")

    def _create_new_schema(self):
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS languages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS snippets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                language_id INTEGER NOT NULL, title TEXT NOT NULL,
                description TEXT, code TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY (language_id) REFERENCES languages(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS snippet_triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snippet_id INTEGER NOT NULL,
                trigger_word TEXT UNIQUE NOT NULL,
                FOREIGN KEY (snippet_id) REFERENCES snippets(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS snippet_tags (
                snippet_id INTEGER NOT NULL, tag_id INTEGER NOT NULL,
                PRIMARY KEY (snippet_id, tag_id),
                FOREIGN KEY (snippet_id) REFERENCES snippets(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE);
        ''')
        self.conn.commit()

    def _seed_defaults(self):
        if self.cursor.execute("SELECT COUNT(*) FROM snippets").fetchone()[0] > 0:
            return
        self.cursor.executemany("INSERT OR IGNORE INTO languages (name) VALUES (?)",
                                [("python",), ("javascript",), ("html",)])
        py_id = self.cursor.execute("SELECT id FROM languages WHERE name='python'").fetchone()[0]
        js_id = self.cursor.execute("SELECT id FROM languages WHERE name='javascript'").fetchone()[0]
        now = datetime.now().isoformat()

        # ──────────────────────────────────────────────
        #  BOILERPLATE
        # ──────────────────────────────────────────────
        boilerplate = [
            (py_id, "Function Definition", "Standard function",
             "def $0(self):\n    pass", "defn, deffunc, funcdef", "boilerplate"),
            (py_id, "Class Definition", "Standard class",
             "class $0:\n    def __init__(self):\n        pass", "classn, classdef", "boilerplate, oop"),
            (py_id, "Main Guard", "Script entry point",
             'if __name__ == "__main__":\n    $0', "main, mainn", "boilerplate"),
            (py_id, "Property", "Python property with getter/setter",
             "class $0:\n    @property\n    def name(self):\n        return self._name\n\n    @name.setter\n    def name(self, value):\n        self._name = value",
             "prop, property", "boilerplate, oop"),
            (py_id, "Dataclass", "Python dataclass definition",
             "from dataclasses import dataclass, field\n\n@dataclass\nclass $0:\n    name: str\n    value: int = 0",
             "dataclass, datacls", "boilerplate, oop"),
            (py_id, "Context Manager", "Custom context manager with enter/exit",
             "class $0:\n    def __enter__(self):\n        return self\n\n    def __exit__(self, exc_type, exc_val, exc_tb):\n        return False",
             "ctxmgr, withmgr, context", "boilerplate, pattern"),
            (js_id, "Arrow Function", "JS arrow function",
             "const $0 = (params) => {\n    \n};", "arrow, fn, func", "boilerplate"),
            (js_id, "Async Function", "Async arrow function",
             "const $0 = async (params) => {\n    try {\n        \n    } catch (err) {\n        console.error(err);\n    }\n};", "asyncfn, async", "boilerplate"),
        ]

        # ──────────────────────────────────────────────
        #  DESIGN PATTERNS
        # ──────────────────────────────────────────────
        patterns = [
            (py_id, "Singleton", "Creational — ensures only one instance exists",
             "class Singleton:\n    _instance = None\n\n    def __new__(cls):\n        if cls._instance is None:\n            cls._instance = super().__new__(cls)\n        return cls._instance\n\n    def __init__(self):\n        if not hasattr(self, '_initialized'):\n            self._initialized = True\n            # init state here\n\n\n# Usage:\n# a = Singleton()\n# b = Singleton()\n# assert a is b  # True",
             "singleton, single", "pattern, creational, oop"),

            (py_id, "Factory Method", "Creational — delegate instantiation to subclasses",
             "from abc import ABC, abstractmethod\n\nclass Product(ABC):\n    @abstractmethod\n    def operation(self) -> str:\n        pass\n\nclass ConcreteProductA(Product):\n    def operation(self) -> str:\n        return \"Result of ConcreteProductA\"\n\nclass ConcreteProductB(Product):\n    def operation(self) -> str:\n        return \"Result of ConcreteProductB\"\n\nclass Creator(ABC):\n    @abstractmethod\n    def _create_product(self) -> Product:\n        pass\n\n    def some_operation(self) -> str:\n        product = self._create_product()\n        return f\"Creator: {product.operation()}\"\n\nclass ConcreteCreatorA(Creator):\n    def _create_product(self) -> Product:\n        return ConcreteProductA()",
             "factory, factorymethod", "pattern, creational, oop"),

            (py_id, "Observer", "Behavioral — publish/subscribe event system",
             "class EventBus:\n    \"\"\"Simple observer / pub-sub pattern.\"\"\"\n    def __init__(self):\n        self._subs: dict[str, list] = {}\n\n    def subscribe(self, event: str, callback):\n        self._subs.setdefault(event, []).append(callback)\n\n    def unsubscribe(self, event: str, callback):\n        if event in self._subs:\n            self._subs[event].remove(callback)\n\n    def publish(self, event: str, *args, **kwargs):\n        for cb in self._subs.get(event, []):\n            cb(*args, **kwargs)\n\n\n# Usage\nbus = EventBus()\nbus.subscribe(\"user_login\", lambda name: print(f\"{name} logged in\"))\nbus.publish(\"user_login\", \"Alice\")",
             "observer, pubsub, eventbus, event", "pattern, behavioral, oop"),

            (py_id, "Strategy", "Behavioral — swap algorithms at runtime",
             "from abc import ABC, abstractmethod\nfrom typing import List\n\nclass SortStrategy(ABC):\n    @abstractmethod\n    def sort(self, data: List) -> List:\n        pass\n\nclass QuickSort(SortStrategy):\n    def sort(self, data: List) -> List:\n        if len(data) <= 1:\n            return data\n        pivot = data[len(data) // 2]\n        left = [x for x in data if x < pivot]\n        mid = [x for x in data if x == pivot]\n        right = [x for x in data if x > pivot]\n        return self.sort(left) + mid + self.sort(right)\n\nclass MergeSort(SortStrategy):\n    def sort(self, data: List) -> List:\n        if len(data) <= 1:\n            return data\n        mid = len(data) // 2\n        left = self.sort(data[:mid])\n        right = self.sort(data[mid:])\n        return self._merge(left, right)\n\n    def _merge(self, a, b):\n        result, i, j = [], 0, 0\n        while i < len(a) and j < len(b):\n            if a[i] <= b[j]:\n                result.append(a[i]); i += 1\n            else:\n                result.append(b[j]); j += 1\n        result.extend(a[i:])\n        result.extend(b[j:])\n        return result\n\nclass Sorter:\n    def __init__(self, strategy: SortStrategy):\n        self._strategy = strategy\n\n    def set_strategy(self, strategy: SortStrategy):\n        self._strategy = strategy\n\n    def execute(self, data: List) -> List:\n        return self._strategy.sort(data)",
             "strategy, strat", "pattern, behavioral, oop"),

            (py_id, "Decorator", "Structural — add behavior without altering the class",
             "from functools import wraps\nimport time\n\n\ndef timer(func):\n    \"\"\"Measure execution time of a function.\"\"\"\n    @wraps(func)\n    def wrapper(*args, **kwargs):\n        start = time.perf_counter()\n        result = func(*args, **kwargs)\n        elapsed = time.perf_counter() - start\n        print(f\"{func.__name__} took {elapsed:.4f}s\")\n        return result\n    return wrapper\n\n\ndef retry(max_attempts=3, delay=1.0, exceptions=(Exception,)):\n    \"\"\"Retry a function on failure with exponential backoff.\"\"\"\n    def decorator(func):\n        @wraps(func)\n        def wrapper(*args, **kwargs):\n            for attempt in range(1, max_attempts + 1):\n                try:\n                    return func(*args, **kwargs)\n                except exceptions as e:\n                    if attempt == max_attempts:\n                        raise\n                    wait = delay * (2 ** (attempt - 1))\n                    print(f\"Attempt {attempt} failed: {e}. Retrying in {wait}s\")\n                    time.sleep(wait)\n        return wrapper\n    return decorator\n\n\n@timer\ndef slow_function():\n    time.sleep(0.5)\n    return \"done\"",
             "decorator, timer, retry", "pattern, structural, oop"),

            (py_id, "Command", "Behavioral — encapsulate actions as objects",
             "class Command:\n    \"\"\"Base command interface.\"\"\"\n    def execute(self): pass\n    def undo(self): pass\n\nclass AddTextCommand(Command):\n    def __init__(self, editor, text):\n        self.editor = editor\n        self.text = text\n\n    def execute(self):\n        self.editor.append(self.text)\n\n    def undo(self):\n        self.editor.lines.pop()\n\n\nclass SimpleEditor:\n    def __init__(self):\n        self.lines: list[str] = []\n        self._history: list[Command] = []\n\n    def run(self, cmd: Command):\n        cmd.execute()\n        self._history.append(cmd)\n\n    def undo(self):\n        if self._history:\n            self._history.pop().undo()\n\n    def append(self, text: str):\n        self.lines.append(text)",
             "command, cmd, undo", "pattern, behavioral, oop"),

            (py_id, "State", "Behavioral — alter behavior when state changes",
             "from abc import ABC, abstractmethod\n\nclass State(ABC):\n    @abstractmethod\n    def handle(self, context): pass\n\nclass LockedState(State):\n    def handle(self, context):\n        print(\"Screen is locked — tap power to unlock\")\n        context.state = UnlockedState()\n\nclass UnlockedState(State):\n    def handle(self, context):\n        print(\"Screen is unlocked — tap power to lock\")\n        context.state = LockedState()\n\nclass Phone:\n    def __init__(self):\n        self.state = LockedState()\n\n    def tap_power(self):\n        self.state.handle(self)",
             "state, statepattern", "pattern, behavioral, oop"),

            (py_id, "Adapter", "Structural — make incompatible interfaces work together",
             "class LegacyPrinter:\n    def print_old(self, text: str):\n        print(f\"[LEGACY] {text}\")\n\nclass ModernPrinter:\n    def print_document(self, title: str, body: str):\n        print(f\"Title: {title}\")\n        print(f\"Body: {body}\")\n\nclass LegacyPrinterAdapter(ModernPrinter):\n    \"\"\"Adapt LegacyPrinter to the ModernPrinter interface.\"\"\"\n    def __init__(self, legacy: LegacyPrinter):\n        self._legacy = legacy\n\n    def print_document(self, title: str, body: str):\n        self._legacy.print_old(f\"{title} — {body}\")",
             "adapter, adapt", "pattern, structural, oop"),

            (py_id, "Facade", "Structural — simplify a complex subsystem",
             "class CPU:\n    def freeze(self): print(\"CPU frozen\")\n    def jump(self, addr): print(f\"CPU jumping to {addr}\")\n    def execute(self): print(\"CPU executing\")\n\nclass Memory:\n    def load(self, addr, data): print(f\"Loading {data} at {addr}\")\n\nclass HardDrive:\n    def read(self, lba, size): return f\"data from sector {lba}\"\n\nclass ComputerFacade:\n    \"\"\"Simplified interface to boot the computer.\"\"\"\n    def __init__(self):\n        self.cpu = CPU()\n        self.mem = Memory()\n        self.hdd = HardDrive()\n\n    def start(self):\n        self.cpu.freeze()\n        self.mem.load(0, self.hdd.read(0, 1024))\n        self.cpu.jump(0)\n        self.cpu.execute()",
             "facade, simplify", "pattern, structural, oop"),

            (py_id, "Template Method", "Behavioral — define skeleton, let subclasses override steps",
             "from abc import ABC, abstractmethod\n\nclass DataProcessor(ABC):\n    \"\"\"Template method: defines the algorithm skeleton.\"\"\"\n    def process(self, data):\n        self._validate(data)\n        result = self._transform(data)\n        self._output(result)\n\n    def _validate(self, data):\n        if not data:\n            raise ValueError(\"Empty data\")\n\n    @abstractmethod\n    def _transform(self, data):\n        pass\n\n    def _output(self, result):\n        print(f\"Result: {result}\")\n\nclass UpperCaseProcessor(DataProcessor):\n    def _transform(self, data):\n        return data.upper()\n\nclass ReverseProcessor(DataProcessor):\n    def _transform(self, data):\n        return data[::-1]",
             "template, template-method, tpl", "pattern, behavioral, oop"),

            (py_id, "Iterator", "Behavioral — traverse collections without exposing internals",
             "from collections.abc import Iterator, Iterable\nfrom typing import Any, List\n\nclass BinaryTree:\n    class _InOrderIterator(Iterator):\n        def __init__(self, root):\n            self._stack = []\n            self._current = root\n\n        def __next__(self):\n            while self._current:\n                self._stack.append(self._current)\n                self._current = self._current.left\n            if not self._stack:\n                raise StopIteration\n            node = self._stack.pop()\n            self._current = node.right\n            return node.value\n\n    class Node:\n        def __init__(self, value, left=None, right=None):\n            self.value = value\n            self.left = left\n            self.right = right\n\n    def __init__(self, root=None):\n        self.root = root\n\n    def __iter__(self):\n        return self._InOrderIterator(self.root)",
             "iterator, iter, traverse", "pattern, behavioral, oop"),

            (py_id, "Repository", "Data access pattern — abstract persistence layer",
             "from abc import ABC, abstractmethod\nfrom typing import Generic, TypeVar, List, Optional\n\nT = TypeVar(\"T\")\n\nclass Repository(ABC, Generic[T]):\n    @abstractmethod\n    def find_by_id(self, id: int) -> Optional[T]: ...\n    @abstractmethod\n    def find_all(self) -> List[T]: ...\n    @abstractmethod\n    def add(self, entity: T) -> T: ...\n    @abstractmethod\n    def delete(self, id: int) -> bool: ...\n\n\nclass InMemoryRepository(Repository[T]):\n    def __init__(self):\n        self._store: dict[int, T] = {}\n        self._next_id = 1\n\n    def find_by_id(self, id: int) -> Optional[T]:\n        return self._store.get(id)\n\n    def find_all(self) -> List[T]:\n        return list(self._store.values())\n\n    def add(self, entity: T) -> T:\n        entity.id = self._next_id\n        self._store[self._next_id] = entity\n        self._next_id += 1\n        return entity\n\n    def delete(self, id: int) -> bool:\n        return self._store.pop(id, None) is not None",
             "repository, repo, dao", "pattern, structural, oop"),
        ]

        # ──────────────────────────────────────────────
        #  DATA STRUCTURES
        # ──────────────────────────────────────────────
        structures = [
            (py_id, "Singly Linked List", "Fundamental linked list with append/remove/reverse",
             "class Node:\n    __slots__ = ('value', 'next')\n    def __init__(self, value, next=None):\n        self.value = value\n        self.next = next\n\nclass LinkedList:\n    def __init__(self):\n        self.head = None\n        self._size = 0\n\n    def append(self, value):\n        new_node = Node(value)\n        if not self.head:\n            self.head = new_node\n        else:\n            cur = self.head\n            while cur.next:\n                cur = cur.next\n            cur.next = new_node\n        self._size += 1\n\n    def prepend(self, value):\n        self.head = Node(value, self.head)\n        self._size += 1\n\n    def remove(self, value):\n        if not self.head:\n            return\n        if self.head.value == value:\n            self.head = self.head.next\n            self._size -= 1\n            return\n        cur = self.head\n        while cur.next:\n            if cur.next.value == value:\n                cur.next = cur.next.next\n                self._size -= 1\n                return\n            cur = cur.next\n\n    def reverse(self):\n        prev, cur = None, self.head\n        while cur:\n            cur.next, prev, cur = prev, cur, cur.next\n        self.head = prev\n\n    def __len__(self):\n        return self._size\n\n    def __iter__(self):\n        cur = self.head\n        while cur:\n            yield cur.value\n            cur = cur.next\n\n    def __repr__(self):\n        return \" -> \".join(map(str, self))",
             "linkedlist, sll, linked", "structure"),

            (py_id, "Doubly Linked List", "Linked list with prev/next pointers for O(1) removal",
             "class Node:\n    __slots__ = ('value', 'prev', 'next')\n    def __init__(self, value, prev=None, next=None):\n        self.value = value\n        self.prev = prev\n        self.next = next\n\nclass DoublyLinkedList:\n    def __init__(self):\n        self.head = None\n        self.tail = None\n        self._size = 0\n\n    def append(self, value):\n        node = Node(value, self.tail)\n        if self.tail:\n            self.tail.next = node\n        else:\n            self.head = node\n        self.tail = node\n        self._size += 1\n\n    def prepend(self, value):\n        node = Node(value, None, self.head)\n        if self.head:\n            self.head.prev = node\n        else:\n            self.tail = node\n        self.head = node\n        self._size += 1\n\n    def remove(self, node):\n        if node.prev:\n            node.prev.next = node.next\n        else:\n            self.head = node.next\n        if node.next:\n            node.next.prev = node.prev\n        else:\n            self.tail = node.prev\n        self._size -= 1\n\n    def __len__(self): return self._size\n\n    def __iter__(self):\n        cur = self.head\n        while cur:\n            yield cur.value\n            cur = cur.next",
             "doublylinked, dll", "structure"),

            (py_id, "Stack (LIFO)", "Stack with push/pop/peek using list",
             "class Stack:\n    \"\"\"LIFO stack implemented with a Python list.\"\"\"\n    __slots__ = ('_data',)\n\n    def __init__(self):\n        self._data: list = []\n\n    def push(self, item):\n        self._data.append(item)\n\n    def pop(self):\n        if self.is_empty():\n            raise IndexError(\"pop from empty stack\")\n        return self._data.pop()\n\n    def peek(self):\n        if self.is_empty():\n            raise IndexError(\"peek from empty stack\")\n        return self._data[-1]\n\n    def is_empty(self) -> bool:\n        return len(self._data) == 0\n\n    def __len__(self) -> int:\n        return len(self._data)\n\n    def __repr__(self) -> str:\n        return f\"Stack({self._data})\"",
             "stack, lifo, push", "structure"),

            (py_id, "Queue (FIFO)", "Queue with enqueue/dequeue using collections.deque",
             "from collections import deque\n\nclass Queue:\n    \"\"\"FIFO queue — O(1) enqueue and dequeue.\"\"\"\n    __slots__ = ('_data',)\n\n    def __init__(self):\n        self._data = deque()\n\n    def enqueue(self, item):\n        self._data.append(item)\n\n    def dequeue(self):\n        if self.is_empty():\n            raise IndexError(\"dequeue from empty queue\")\n        return self._data.popleft()\n\n    def peek(self):\n        if self.is_empty():\n            raise IndexError(\"peek from empty queue\")\n        return self._data[0]\n\n    def is_empty(self) -> bool:\n        return len(self._data) == 0\n\n    def __len__(self) -> int:\n        return len(self._data)\n\n    def __repr__(self) -> str:\n        return f\"Queue({list(self._data)})\"",
             "queue, fifo, enqueue", "structure"),

            (py_id, "Binary Search Tree", "BST with insert/search/delete/in-order traversal",
             "class BSTNode:\n    __slots__ = ('key', 'val', 'left', 'right')\n    def __init__(self, key, val=None):\n        self.key = key\n        self.val = val\n        self.left = None\n        self.right = None\n\nclass BST:\n    def __init__(self):\n        self.root = None\n\n    def insert(self, key, val=None):\n        self.root = self._insert(self.root, key, val)\n\n    def _insert(self, node, key, val):\n        if not node:\n            return BSTNode(key, val)\n        if key < node.key:\n            node.left = self._insert(node.left, key, val)\n        elif key > node.key:\n            node.right = self._insert(node.right, key, val)\n        else:\n            node.val = val\n        return node\n\n    def search(self, key):\n        node = self.root\n        while node:\n            if key == node.key: return node.val\n            node = node.left if key < node.key else node.right\n        return None\n\n    def in_order(self):\n        result = []\n        self._in_order(self.root, result)\n        return result\n\n    def _in_order(self, node, result):\n        if node:\n            self._in_order(node.left, result)\n            result.append(node.key)\n            self._in_order(node.right, result)\n\n    def delete(self, key):\n        self.root = self._delete(self.root, key)\n\n    def _delete(self, node, key):\n        if not node: return None\n        if key < node.key:\n            node.left = self._delete(node.left, key)\n        elif key > node.key:\n            node.right = self._delete(node.right, key)\n        else:\n            if not node.left: return node.right\n            if not node.right: return node.left\n            succ = self._min_node(node.right)\n            node.key, node.val = succ.key, succ.val\n            node.right = self._delete(node.right, succ.key)\n        return node\n\n    def _min_node(self, node):\n        while node.left: node = node.left\n        return node",
             "bst, binarysearchtree, binarytree", "structure, tree"),

            (py_id, "Min-Heap / Priority Queue", "Binary min-heap with push/pop in O(log n)",
             "import heapq\n\nclass MinHeap:\n    \"\"\"Min-heap wrapper around heapq for clarity.\"\"\"\n    def __init__(self):\n        self._data: list = []\n\n    def push(self, item, priority: float = 0.0):\n        heapq.heappush(self._data, (priority, item))\n\n    def pop(self):\n        if not self._data:\n            raise IndexError(\"pop from empty heap\")\n        return heapq.heappop(self._data)[1]\n\n    def peek(self):\n        if not self._data:\n            raise IndexError(\"peek from empty heap\")\n        return self._data[0][1]\n\n    def __len__(self) -> int:\n        return len(self._data)\n\n    def __bool__(self) -> bool:\n        return bool(self._data)\n\n    def to_sorted_list(self) -> list:\n        return [item for _, item in sorted(self._data)]",
             "heap, minheap, priorityqueue, pq", "structure"),

            (py_id, "Hash Map (Chaining)", "Hash table with separate chaining collision resolution",
             "class HashMap:\n    \"\"\"Hash map with separate chaining. O(1) amortized CRUD.\"\"\"\n    def __init__(self, capacity: int = 16, load_factor: float = 0.75):\n        self._capacity = capacity\n        self._load_factor = load_factor\n        self._buckets: list[list] = [[] for _ in range(capacity)]\n        self._size = 0\n\n    def _hash(self, key) -> int:\n        return hash(key) % self._capacity\n\n    def __setitem__(self, key, value):\n        idx = self._hash(key)\n        bucket = self._buckets[idx]\n        for i, (k, _) in enumerate(bucket):\n            if k == key:\n                bucket[i] = (key, value)\n                return\n        bucket.append((key, value))\n        self._size += 1\n        if self._size / self._capacity > self._load_factor:\n            self._resize()\n\n    def __getitem__(self, key):\n        for k, v in self._buckets[self._hash(key)]:\n            if k == key: return v\n        raise KeyError(key)\n\n    def __delitem__(self, key):\n        bucket = self._buckets[self._hash(key)]\n        for i, (k, _) in enumerate(bucket):\n            if k == key:\n                del bucket[i]\n                self._size -= 1\n                return\n        raise KeyError(key)\n\n    def __contains__(self, key) -> bool:\n        return any(k == key for k, _ in self._buckets[self._hash(key)])\n\n    def __len__(self) -> int:\n        return self._size\n\n    def _resize(self):\n        old = self._buckets\n        self._capacity *= 2\n        self._buckets = [[] for _ in range(self._capacity)]\n        self._size = 0\n        for bucket in old:\n            for k, v in bucket:\n                self[k] = v",
             "hashmap, hashmapchain, hashtable", "structure"),

            (py_id, "Graph (Adjacency List)", "Directed graph with BFS, DFS, topological sort",
             "from collections import deque\n\nclass Graph:\n    \"\"\"Directed graph using adjacency list representation.\"\"\"\n    def __init__(self):\n        self._adj: dict[str, list[str]] = {}\n\n    def add_edge(self, u: str, v: str):\n        self._adj.setdefault(u, []).append(v)\n        self._adj.setdefault(v, [])  # ensure node exists\n\n    def neighbors(self, node: str) -> list[str]:\n        return self._adj.get(node, [])\n\n    def bfs(self, start: str) -> list[str]:\n        visited, queue, order = {start}, deque([start]), []\n        while queue:\n            node = queue.popleft()\n            order.append(node)\n            for nb in self.neighbors(node):\n                if nb not in visited:\n                    visited.add(nb)\n                    queue.append(nb)\n        return order\n\n    def dfs(self, start: str) -> list[str]:\n        visited, order = set(), []\n        def _dfs(node):\n            visited.add(node)\n            order.append(node)\n            for nb in self.neighbors(node):\n                if nb not in visited:\n                    _dfs(nb)\n        _dfs(start)\n        return order\n\n    def topological_sort(self) -> list[str]:\n        in_deg = {n: 0 for n in self._adj}\n        for u in self._adj:\n            for v in self._adj[u]:\n                in_deg[v] += 1\n        queue = deque([n for n, d in in_deg.items() if d == 0])\n        order = []\n        while queue:\n            node = queue.popleft()\n            order.append(node)\n            for nb in self.neighbors(node):\n                in_deg[nb] -= 1\n                if in_deg[nb] == 0:\n                    queue.append(nb)\n        if len(order) != len(self._adj):\n            raise ValueError(\"Graph has a cycle\")\n        return order\n\n    def __repr__(self):\n        return f\"Graph({self._adj})\"",
             "graph, adjlist, dijkstra", "structure, graph"),

            (py_id, "Trie (Prefix Tree)", "Fast autocomplete / prefix search structure",
             "class TrieNode:\n    __slots__ = ('children', 'is_end')\n    def __init__(self):\n        self.children: dict[str, 'TrieNode'] = {}\n        self.is_end = False\n\nclass Trie:\n    \"\"\"Prefix tree for O(m) insert/search where m = word length.\"\"\"\n    def __init__(self):\n        self.root = TrieNode()\n\n    def insert(self, word: str):\n        node = self.root\n        for ch in word:\n            if ch not in node.children:\n                node.children[ch] = TrieNode()\n            node = node.children[ch]\n        node.is_end = True\n\n    def search(self, word: str) -> bool:\n        node = self._find(word)\n        return node is not None and node.is_end\n\n    def starts_with(self, prefix: str) -> bool:\n        return self._find(prefix) is not None\n\n    def _find(self, prefix: str):\n        node = self.root\n        for ch in prefix:\n            if ch not in node.children:\n                return None\n            node = node.children[ch]\n        return node\n\n    def autocomplete(self, prefix: str, limit: int = 10) -> list[str]:\n        node = self._find(prefix)\n        if not node:\n            return []\n        results = []\n        self._collect(node, prefix, results, limit)\n        return results\n\n    def _collect(self, node, prefix, results, limit):\n        if len(results) >= limit:\n            return\n        if node.is_end:\n            results.append(prefix)\n        for ch, child in sorted(node.children.items()):\n            self._collect(child, prefix + ch, results, limit)",
             "trie, prefixtree, autocomplete", "structure, tree"),

            (py_id, "LRU Cache", "O(1) get/put least-recently-used cache using OrderedDict",
             "from collections import OrderedDict\n\nclass LRUCache:\n    \"\"\"Least Recently Used cache — O(1) get and put.\"\"\"\n    def __init__(self, capacity: int):\n        if capacity <= 0:\n            raise ValueError(\"Capacity must be positive\")\n        self._capacity = capacity\n        self._cache: OrderedDict = OrderedDict()\n\n    def get(self, key):\n        if key not in self._cache:\n            return -1\n        self._cache.move_to_end(key)  # mark as recently used\n        return self._cache[key]\n\n    def put(self, key, value):\n        if key in self._cache:\n            self._cache.move_to_end(key)\n        self._cache[key] = value\n        if len(self._cache) > self._capacity:\n            self._cache.popitem(last=False)  # evict LRU\n\n    def __len__(self) -> int:\n        return len(self._cache)\n\n    def __repr__(self) -> str:\n        return f\"LRUCache({list(self._cache.keys())})\"",
             "lru, lrucache, cache", "structure"),

            (py_id, "Union-Find (Disjoint Set)", "Efficient connected-component tracking with path compression",
             "class UnionFind:\n    \"\"\"Disjoint Set Union with path compression + union by rank.\"\"\"\n    def __init__(self, n: int):\n        self.parent = list(range(n))\n        self.rank = [0] * n\n        self._count = n\n\n    def find(self, x: int) -> int:\n        # Path compression (iterative)\n        root = x\n        while self.parent[root] != root:\n            root = self.parent[root]\n        while self.parent[x] != root:\n            self.parent[x], x = root, self.parent[x]\n        return root\n\n    def union(self, x: int, y: int) -> bool:\n        rx, ry = self.find(x), self.find(y)\n        if rx == ry:\n            return False\n        # Union by rank\n        if self.rank[rx] < self.rank[ry]:\n            rx, ry = ry, rx\n        self.parent[ry] = rx\n        if self.rank[rx] == self.rank[ry]:\n            self.rank[rx] += 1\n        self._count -= 1\n        return True\n\n    def connected(self, x: int, y: int) -> bool:\n        return self.find(x) == self.find(y)\n\n    def count(self) -> int:\n        return self._count",
             "unionfind, dsu, disjoint", "structure"),
        ]

        # ──────────────────────────────────────────────
        #  ALGORITHMS
        # ──────────────────────────────────────────────
        algorithms = [
            (py_id, "Binary Search", "O(log n) search on sorted array",
             "def binary_search(arr: list, target) -> int:\n    \"\"\"Return index of target in sorted arr, or -1 if not found.\"\"\"\n    lo, hi = 0, len(arr) - 1\n    while lo <= hi:\n        mid = lo + (hi - lo) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1\n\n\ndef binary_search_left(arr: list, target) -> int:\n    \"\"\"Leftmost insertion point (bisect_left equivalent).\"\"\"\n    lo, hi = 0, len(arr)\n    while lo < hi:\n        mid = (lo + hi) // 2\n        if arr[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid\n    return lo",
             "binsearch, binarysearch, bsearch", "algorithm, search"),

            (py_id, "Quick Sort", "O(n log n) average, in-place partition sort",
             "import random\n\ndef quick_sort(arr: list) -> list:\n    \"\"\"Quick sort with random pivot — O(n log n) average.\"\"\"\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[random.randint(0, len(arr) - 1)]\n    left  = [x for x in arr if x < pivot]\n    mid   = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quick_sort(left) + mid + quick_sort(right)\n\n\ndef quick_sort_inplace(arr: list, lo: int = 0, hi: int = None):\n    \"\"\"In-place quick sort (no extra lists).\"\"\"\n    if hi is None:\n        hi = len(arr) - 1\n    if lo >= hi:\n        return\n    pivot = arr[(lo + hi) // 2]\n    i, j = lo, hi\n    while i <= j:\n        while arr[i] < pivot: i += 1\n        while arr[j] > pivot: j -= 1\n        if i <= j:\n            arr[i], arr[j] = arr[j], arr[i]\n            i += 1\n            j -= 1\n    quick_sort_inplace(arr, lo, j)\n    quick_sort_inplace(arr, i, hi)",
             "quicksort, qsort, sort", "algorithm, sort"),

            (py_id, "Merge Sort", "O(n log n) stable, divide-and-conquer sort",
             "def merge_sort(arr: list) -> list:\n    \"\"\"Stable O(n log n) merge sort.\"\"\"\n    if len(arr) <= 1:\n        return arr\n    mid = len(arr) // 2\n    left = merge_sort(arr[:mid])\n    right = merge_sort(arr[mid:])\n    return _merge(left, right)\n\n\ndef _merge(a: list, b: list) -> list:\n    result, i, j = [], 0, 0\n    while i < len(a) and j < len(b):\n        if a[i] <= b[j]:\n            result.append(a[i]); i += 1\n        else:\n            result.append(b[j]); j += 1\n    result.extend(a[i:])\n    result.extend(b[j:])\n    return result",
             "mergesort, msort, mergesrt", "algorithm, sort"),

            (py_id, "BFS (Breadth-First Search)", "Level-order graph/tree traversal — O(V+E)",
             "from collections import deque\n\ndef bfs(graph: dict, start) -> list:\n    \"\"\"Breadth-first search returning nodes in visit order.\"\"\"\n    visited = {start}\n    queue = deque([start])\n    order = []\n    while queue:\n        node = queue.popleft()\n        order.append(node)\n        for neighbor in graph.get(node, []):\n            if neighbor not in visited:\n                visited.add(neighbor)\n                queue.append(neighbor)\n    return order\n\n\ndef bfs_shortest_path(graph: dict, start, goal) -> list | None:\n    \"\"\"Shortest path (unweighted) via BFS.\"\"\"\n    visited = {start}\n    queue = deque([(start, [start])])\n    while queue:\n        node, path = queue.popleft()\n        if node == goal:\n            return path\n        for nb in graph.get(node, []):\n            if nb not in visited:\n                visited.add(nb)\n                queue.append((nb, path + [nb]))\n    return None",
             "bfs, breadthfirst, shortestpath", "algorithm, search, graph"),

            (py_id, "DFS (Depth-First Search)", "Graph/tree traversal — O(V+E)",
             "def dfs(graph: dict, start) -> list:\n    \"\"\"Iterative depth-first search.\"\"\"\n    visited = set()\n    stack = [start]\n    order = []\n    while stack:\n        node = stack.pop()\n        if node in visited:\n            continue\n        visited.add(node)\n        order.append(node)\n        for nb in reversed(graph.get(node, [])):\n            if nb not in visited:\n                stack.append(nb)\n    return order\n\n\ndef dfs_recursive(graph: dict, start, visited=None, order=None):\n    \"\"\"Recursive depth-first search.\"\"\"\n    if visited is None:\n        visited, order = set(), []\n    visited.add(start)\n    order.append(start)\n    for nb in graph.get(start, []):\n        if nb not in visited:\n            dfs_recursive(graph, nb, visited, order)\n    return order",
             "dfs, depthfirst", "algorithm, search, graph"),

            (py_id, "Dijkstra's Algorithm", "Shortest path on weighted graph — O((V+E) log V)",
             "import heapq\nfrom math import inf\n\ndef dijkstra(graph: dict, start: str) -> dict:\n    \"\"\"Shortest distances from start to all reachable nodes.\"\"\"\n    dist = {node: inf for node in graph}\n    dist[start] = 0\n    pq = [(0, start)]\n    visited = set()\n    while pq:\n        d, u = heapq.heappop(pq)\n        if u in visited:\n            continue\n        visited.add(u)\n        for v, w in graph[u]:\n            if d + w < dist[v]:\n                dist[v] = d + w\n                heapq.heappush(pq, (dist[v], v))\n    return dist\n\n\n# Example graph (adjacency list: node -> [(neighbor, weight), ...])\n# g = {\n#     'A': [('B', 1), ('C', 4)],\n#     'B': [('C', 2), ('D', 5)],\n#     'C': [('D', 1)],\n#     'D': []\n# }\n# print(dijkstra(g, 'A'))  # {'A': 0, 'B': 1, 'C': 3, 'D': 4}",
             "dijkstra, shortest, weighted", "algorithm, graph, search"),

            (py_id, "Topological Sort", "Linear ordering for DAG — O(V+E)",
             "from collections import deque\n\ndef topological_sort(graph: dict) -> list:\n    \"\"\"Kahn's algorithm for topological sorting.\"\"\"\n    in_deg = {node: 0 for node in graph}\n    for u in graph:\n        for v in graph[u]:\n            in_deg[v] = in_deg.get(v, 0) + 1\n    queue = deque([n for n, d in in_deg.items() if d == 0])\n    order = []\n    while queue:\n        node = queue.popleft()\n        order.append(node)\n        for nb in graph[node]:\n            in_deg[nb] -= 1\n            if in_deg[nb] == 0:\n                queue.append(nb)\n    if len(order) != len(graph):\n        raise ValueError(\"Cycle detected — not a DAG\")\n    return order",
             "toposort, topological, kahn", "algorithm, graph, sort"),

            (py_id, "Kadane's Algorithm", "Maximum subarray sum — O(n)",
             "def kadane(arr: list) -> int:\n    \"\"\"Maximum subarray sum in O(n) time, O(1) space.\"\"\"\n    if not arr:\n        return 0\n    max_sum = current = arr[0]\n    for x in arr[1:]:\n        current = max(x, current + x)\n        max_sum = max(max_sum, current)\n    return max_sum\n\n\ndef kadane_subarray(arr: list) -> tuple[int, int, int]:\n    \"\"\"Return (max_sum, start_index, end_index).\"\"\"\n    max_sum = current = arr[0]\n    start = end = temp = 0\n    for i in range(1, len(arr)):\n        if arr[i] > current + arr[i]:\n            current = arr[i]\n            temp = i\n        else:\n            current += arr[i]\n        if current > max_sum:\n            max_sum = current\n            start, end = temp, i\n    return max_sum, start, end",
             "kadane, maxsubarray, subarray", "algorithm"),

            (py_id, "Two Pointers", "Common two-pointer patterns",
             "def two_sum_sorted(arr: list, target: int) -> tuple[int, int] | None:\n    \"\"\"Find two numbers that sum to target in a sorted array — O(n).\"\"\"\n    lo, hi = 0, len(arr) - 1\n    while lo < hi:\n        s = arr[lo] + arr[hi]\n        if s == target:\n            return lo, hi\n        elif s < target:\n            lo += 1\n        else:\n            hi -= 1\n    return None\n\n\ndef is_palindrome(s: str) -> bool:\n    \"\"\"Check if string is a palindrome — O(n).\"\"\"\n    lo, hi = 0, len(s) - 1\n    while lo < hi:\n        if s[lo] != s[hi]:\n            return False\n        lo += 1\n        hi -= 1\n    return True\n\n\ndef remove_duplicates_sorted(arr: list) -> int:\n    \"\"\"Remove duplicates in-place, return new length — O(n).\"\"\"\n    if not arr:\n        return 0\n    write = 1\n    for read in range(1, len(arr)):\n        if arr[read] != arr[write - 1]:\n            arr[write] = arr[read]\n            write += 1\n    return write",
             "twopointers, 2pointers, pointers", "algorithm"),

            (py_id, "Sliding Window", "Fixed and variable window patterns",
             "def max_sum_subarray_k(arr: list, k: int) -> int:\n    \"\"\"Maximum sum of any subarray of length k — O(n).\"\"\"\n    if len(arr) < k:\n        return sum(arr)\n    window_sum = sum(arr[:k])\n    max_sum = window_sum\n    for i in range(k, len(arr)):\n        window_sum += arr[i] - arr[i - k]\n        max_sum = max(max_sum, window_sum)\n    return max_sum\n\n\ndef longest_substring_without_repeats(s: str) -> int:\n    \"\"\"Length of longest substring with all unique chars — O(n).\"\"\"\n    seen: dict[str, int] = {}\n    start = max_len = 0\n    for i, ch in enumerate(s):\n        if ch in seen and seen[ch] >= start:\n            start = seen[ch] + 1\n        seen[ch] = i\n        max_len = max(max_len, i - start + 1)\n    return max_len",
             "slidingwindow, sliding, window", "algorithm"),

            (py_id, "Fibonacci (Memoized + DP)", "Memoized recursion and bottom-up DP",
             "from functools import lru_cache\n\n@lru_cache(maxsize=None)\ndef fib_memo(n: int) -> int:\n    \"\"\"O(n) time with memoization, O(n) space for cache.\"\"\"\n    if n < 2:\n        return n\n    return fib_memo(n - 1) + fib_memo(n - 2)\n\n\ndef fib_dp(n: int) -> int:\n    \"\"\"O(n) time, O(1) space — bottom-up dynamic programming.\"\"\"\n    if n < 2:\n        return n\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b\n\n\ndef fib_matrix(n: int) -> int:\n    \"\"\"O(log n) via matrix exponentiation.\"\"\"\n    def mat_mul(A, B):\n        return [\n            [A[0][0]*B[0][0] + A[0][1]*B[1][0], A[0][0]*B[0][1] + A[0][1]*B[1][1]],\n            [A[1][0]*B[0][0] + A[1][1]*B[1][0], A[1][0]*B[0][1] + A[1][1]*B[1][1]],\n        ]\n    result = [[1, 0], [0, 1]]\n    base = [[1, 1], [1, 0]]\n    k = n\n    while k > 0:\n        if k % 2 == 1:\n            result = mat_mul(result, base)\n        base = mat_mul(base, base)\n        k //= 2\n    return result[0][1]",
             "fibonacci, fib, memo, dp", "algorithm, dp"),

            (py_id, "0/1 Knapsack", "Classic DP — O(n*W) time and space",
             "def knapsack_01(weights: list, values: list, capacity: int) -> int:\n    \"\"\"0/1 Knapsack — select items for maximum value within capacity.\"\"\"\n    n = len(weights)\n    dp = [0] * (capacity + 1)\n    for i in range(n):\n        w, v = weights[i], values[i]\n        for c in range(capacity, w - 1, -1):\n            dp[c] = max(dp[c], dp[c - w] + v)\n    return dp[capacity]\n\n\ndef knapsack_with_items(weights: list, values: list, capacity: int) -> tuple[int, list[int]]:\n    \"\"\"Returns (max_value, list_of_selected_indices).\"\"\"\n    n = len(weights)\n    dp = [[0] * (capacity + 1) for _ in range(n + 1)]\n    for i in range(1, n + 1):\n        for c in range(capacity + 1):\n            dp[i][c] = dp[i - 1][c]\n            if weights[i - 1] <= c:\n                dp[i][c] = max(dp[i][c], dp[i - 1][c - weights[i - 1]] + values[i - 1])\n    # Backtrack to find items\n    selected, c = [], capacity\n    for i in range(n, 0, -1):\n        if dp[i][c] != dp[i - 1][c]:\n            selected.append(i - 1)\n            c -= weights[i - 1]\n    return dp[n][capacity], selected[::-1]",
             "knapsack, knap, 01knapsack", "algorithm, dp"),

            (py_id, "Longest Increasing Subsequence", "Patience sorting — O(n log n)",
             "import bisect\n\ndef lis_length(arr: list) -> int:\n    \"\"\"Length of the longest increasing subsequence — O(n log n).\"\"\"\n    tails: list[int] = []\n    for x in arr:\n        pos = bisect.bisect_left(tails, x)\n        if pos == len(tails):\n            tails.append(x)\n        else:\n            tails[pos] = x\n    return len(tails)\n\n\ndef lis(arr: list) -> list:\n    \"\"\"Reconstruct one longest increasing subsequence.\"\"\"\n    if not arr:\n        return []\n    tails: list[int] = []\n    indices: list[int] = []\n    prev: list[int] = [-1] * len(arr)\n    for i, x in enumerate(arr):\n        pos = bisect.bisect_left(tails, x)\n        if pos == len(tails):\n            tails.append(x)\n            indices.append(i)\n        else:\n            tails[pos] = x\n            indices[pos] = i\n        if pos > 0:\n            prev[i] = indices[pos - 1]\n    # Reconstruct\n    result, k = [], indices[-1]\n    while k != -1:\n        result.append(arr[k])\n        k = prev[k]\n    return result[::-1]",
             "lis, longestincreasing, subsequence", "algorithm, dp"),

            (py_id, "Matrix Exponentiation", "Fast power for matrix-based recurrences — O(log n)",
             "def mat_mul(A, B, mod=None):\n    \"\"\"Multiply two square matrices.\"\"\"\n    n = len(A)\n    C = [[0] * n for _ in range(n)]\n    for i in range(n):\n        for k in range(n):\n            if A[i][k] == 0:\n                continue\n            for j in range(n):\n                C[i][j] += A[i][k] * B[k][j]\n            if mod:\n                C[i][j] %= mod\n    return C\n\n\ndef mat_pow(M, power, mod=None):\n    \"\"\"Matrix exponentiation in O(n^3 log p).\"\"\"\n    n = len(M)\n    result = [[int(i == j) for j in range(n)] for i in range(n)]  # identity\n    base = [row[:] for row in M]\n    while power > 0:\n        if power & 1:\n            result = mat_mul(result, base, mod)\n        base = mat_mul(base, base, mod)\n        power >>= 1\n    return result",
             "matpow, matrixpow, matrixexp", "algorithm, math"),
        ]

        # ──────────────────────────────────────────────
        #  JS DATA STRUCTURES & ALGORITHMS
        # ──────────────────────────────────────────────
        js_snippets = [
            (js_id, "JS Linked List", "Singly linked list in JavaScript",
             "class ListNode {\n  constructor(val, next = null) {\n    this.val = val;\n    this.next = next;\n  }\n}\n\nclass LinkedList {\n  constructor() {\n    this.head = null;\n    this.size = 0;\n  }\n  append(val) {\n    const node = new ListNode(val);\n    if (!this.head) { this.head = node; }\n    else {\n      let cur = this.head;\n      while (cur.next) cur = cur.next;\n      cur.next = node;\n    }\n    this.size++;\n  }\n  toArray() {\n    const arr = [];\n    let cur = this.head;\n    while (cur) { arr.push(cur.val); cur = cur.next; }\n    return arr;\n  }\n}",
             "linkedlist, jslist", "structure"),

            (js_id, "JS LRU Cache", "O(1) LRU cache using Map (insertion-order)",
             "class LRUCache {\n  constructor(capacity) {\n    this.capacity = capacity;\n    this.cache = new Map();\n  }\n  get(key) {\n    if (!this.cache.has(key)) return -1;\n    const val = this.cache.get(key);\n    this.cache.delete(key);\n    this.cache.set(key, val);\n    return val;\n  }\n  put(key, value) {\n    if (this.cache.has(key)) this.cache.delete(key);\n    this.cache.set(key, value);\n    if (this.cache.size > this.capacity) {\n      const lru = this.cache.keys().next().value;\n      this.cache.delete(lru);\n    }\n  }\n}",
             "lrucache, jscache", "structure"),

            (js_id, "JS Debounce & Throttle", "Performance patterns for event handlers",
             "function debounce(fn, delay) {\n  let timer;\n  return function (...args) {\n    clearTimeout(timer);\n    timer = setTimeout(() => fn.apply(this, args), delay);\n  };\n}\n\nfunction throttle(fn, limit) {\n  let inThrottle = false;\n  return function (...args) {\n    if (!inThrottle) {\n      fn.apply(this, args);\n      inThrottle = true;\n      setTimeout(() => (inThrottle = false), limit);\n    }\n  };\n}\n\n// Usage:\n// window.addEventListener('resize', debounce(handleResize, 300));\n// window.addEventListener('scroll', throttle(handleScroll, 100));",
             "debounce, throttle, perf", "pattern, performance"),

            (js_id, "JS Quick Sort", "In-place quicksort",
             "function quickSort(arr, lo = 0, hi = arr.length - 1) {\n  if (lo >= hi) return arr;\n  const pivot = arr[Math.floor((lo + hi) / 2)];\n  let i = lo, j = hi;\n  while (i <= j) {\n    while (arr[i] < pivot) i++;\n    while (arr[j] > pivot) j--;\n    if (i <= j) {\n      [arr[i], arr[j]] = [arr[j], arr[i]];\n      i++; j--;\n    }\n  }\n  quickSort(arr, lo, j);\n  quickSort(arr, i, hi);\n  return arr;\n}",
             "quicksort, jsqsort", "algorithm, sort"),
        ]

        # ──────────────────────────────────────────────
        #  FLATTEN ALL INTO DB
        # ──────────────────────────────────────────────
        all_snippets = boilerplate + patterns + structures + algorithms + js_snippets

        # Insert snippets
        rows = []
        for lang_id, title, desc, code, _, _ in all_snippets:
            rows.append((lang_id, title, desc, code, now, now))
        self.cursor.executemany(
            "INSERT INTO snippets (language_id,title,description,code,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            rows)

        # Insert triggers
        trigger_rows = []
        for idx, (lang_id, title, desc, code, triggers_str, tags_str) in enumerate(all_snippets):
            snip_id = self.cursor.execute(
                "SELECT id FROM snippets WHERE title=?", (title,)).fetchone()[0]
            for t in triggers_str.split(", "):
                if t.strip():
                    trigger_rows.append((snip_id, t.strip().lower()))
        self.cursor.executemany(
            "INSERT OR IGNORE INTO snippet_triggers (snippet_id,trigger_word) VALUES (?,?)",
            trigger_rows)

        # Insert tags
        all_tags = set()
        for _, _, _, _, _, tags_str in all_snippets:
            for t in tags_str.split(", "):
                if t.strip():
                    all_tags.add(t.strip().lower())
        self.cursor.executemany(
            "INSERT OR IGNORE INTO tags (name) VALUES (?)",
            [(t,) for t in sorted(all_tags)])

        # Insert snippet-tag links
        tag_rows = []
        for lang_id, title, desc, code, _, tags_str in all_snippets:
            snip_id = self.cursor.execute(
                "SELECT id FROM snippets WHERE title=?", (title,)).fetchone()[0]
            for t in tags_str.split(", "):
                if t.strip():
                    tag_name = t.strip().lower()
                    tag_id = self.cursor.execute(
                        "SELECT id FROM tags WHERE name=?", (tag_name,)).fetchone()[0]
                    tag_rows.append((snip_id, tag_id))
        self.cursor.executemany(
            "INSERT OR IGNORE INTO snippet_tags (snippet_id,tag_id) VALUES (?,?)",
            tag_rows)

        self.conn.commit()

    # ---------- CRUD ----------
    def add_snippet(self, language, title, description, triggers_list, tags_list, code):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO languages (name) VALUES (?)", (language.lower(),))
            lang_id = self.cursor.execute("SELECT id FROM languages WHERE name=?", (language.lower(),)).fetchone()[0]
            now = datetime.now().isoformat()
            self.cursor.execute(
                "INSERT INTO snippets (language_id,title,description,code,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (lang_id, title, description, code, now, now))
            snip_id = self.cursor.execute("SELECT last_insert_rowid()").fetchone()[0]
            for t in triggers_list:
                if t.strip():
                    self.cursor.execute(
                        "INSERT OR IGNORE INTO snippet_triggers (snippet_id,trigger_word) VALUES (?,?)",
                        (snip_id, t.strip().lower()))
            for t in tags_list:
                if t.strip():
                    self.cursor.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (t.strip().lower(),))
                    tag_id = self.cursor.execute("SELECT id FROM tags WHERE name=?",
                                                  (t.strip().lower(),)).fetchone()[0]
                    self.cursor.execute("INSERT OR IGNORE INTO snippet_tags (snippet_id,tag_id) VALUES (?,?)",
                                        (snip_id, tag_id))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            QMessageBox.warning(None, "DB Error",
                                f"Constraint failed: {e}\nLikely a duplicate trigger word.")
            self.conn.rollback()
            return False

    def get_snippet_by_id(self, snippet_id):
        """Return full snippet data for editing."""
        row = self.cursor.execute("SELECT language_id,title,description,code FROM snippets WHERE id=?",
                                  (snippet_id,)).fetchone()
        if not row:
            return None
        lang_id, title, desc, code = row
        lang_name = self.cursor.execute("SELECT name FROM languages WHERE id=?", (lang_id,)).fetchone()[0]
        triggers = [r[0] for r in self.cursor.execute(
            "SELECT trigger_word FROM snippet_triggers WHERE snippet_id=?", (snippet_id,)).fetchall()]
        tags = [r[0] for r in self.cursor.execute(
            "SELECT t.name FROM tags t JOIN snippet_tags st ON t.id=st.tag_id WHERE st.snippet_id=?",
            (snippet_id,)).fetchall()]
        return {"language": lang_name, "title": title, "description": desc,
                "triggers": triggers, "tags": tags, "code": code}

    def update_snippet(self, snippet_id, language, title, description, triggers_list, tags_list, code):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO languages (name) VALUES (?)", (language.lower(),))
            lang_id = self.cursor.execute("SELECT id FROM languages WHERE name=?",
                                          (language.lower(),)).fetchone()[0]
            now = datetime.now().isoformat()
            self.cursor.execute(
                "UPDATE snippets SET language_id=?,title=?,description=?,code=?,updated_at=? WHERE id=?",
                (lang_id, title, description, code, now, snippet_id))
            self.cursor.execute("DELETE FROM snippet_triggers WHERE snippet_id=?", (snippet_id,))
            for t in triggers_list:
                if t.strip():
                    self.cursor.execute(
                        "INSERT OR IGNORE INTO snippet_triggers (snippet_id,trigger_word) VALUES (?,?)",
                        (snippet_id, t.strip().lower()))
            self.cursor.execute("DELETE FROM snippet_tags WHERE snippet_id=?", (snippet_id,))
            for t in tags_list:
                if t.strip():
                    self.cursor.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (t.strip().lower(),))
                    tag_id = self.cursor.execute("SELECT id FROM tags WHERE name=?",
                                                  (t.strip().lower(),)).fetchone()[0]
                    self.cursor.execute("INSERT OR IGNORE INTO snippet_tags (snippet_id,tag_id) VALUES (?,?)",
                                        (snippet_id, tag_id))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            QMessageBox.warning(None, "DB Error", f"Update failed: {e}")
            self.conn.rollback()
            return False

    # ---------- queries ----------
    def get_all_triggers(self):
        self.cursor.execute(
            'SELECT st.trigger_word, s.code FROM snippet_triggers st JOIN snippets s ON st.snippet_id=s.id')
        return {row[0].lower(): row[1] for row in self.cursor.fetchall()}

    def get_languages(self):
        self.cursor.execute("SELECT name FROM languages ORDER BY name")
        return [row[0].capitalize() for row in self.cursor.fetchall()]

    def get_tags_for_language(self, language):
        self.cursor.execute('''
            SELECT DISTINCT t.name FROM tags t
            JOIN snippet_tags st ON t.id=st.tag_id
            JOIN snippets s ON st.snippet_id=s.id
            JOIN languages l ON s.language_id=l.id
            WHERE l.name=? ORDER BY t.name
        ''', (language.lower(),))
        return ["All Tags"] + [row[0].capitalize() for row in self.cursor.fetchall()]

    def get_snippets_filtered(self, language, tag="all tags"):
        query = '''
            SELECT s.id,s.title,s.description,
                   GROUP_CONCAT(st.trigger_word,', '),
                   GROUP_CONCAT(t.name,', ')
            FROM snippets s
            LEFT JOIN snippet_triggers st ON s.id=st.snippet_id
            LEFT JOIN snippet_tags stg ON s.id=stg.snippet_id
            LEFT JOIN tags t ON stg.tag_id=t.id
            JOIN languages l ON s.language_id=l.id
            WHERE l.name=?
        '''
        params = [language.lower()]
        if tag.lower() != "all tags":
            query += " AND EXISTS (SELECT 1 FROM snippet_tags st2 JOIN tags t2 ON st2.tag_id=t2.id WHERE st2.snippet_id=s.id AND t2.name=?)"
            params.append(tag.lower())
        query += " GROUP BY s.id ORDER BY s.title"
        return self.cursor.execute(query, params).fetchall()

    def delete_snippet(self, snippet_id):
        self.cursor.execute("DELETE FROM snippets WHERE id=?", (snippet_id,))
        self.conn.commit()

    # ---------- export / import ----------
    def export_to_json(self, filepath):
        snippets = self.cursor.execute(
            '''SELECT s.id,l.name,s.title,s.description,s.code,s.created_at,s.updated_at
               FROM snippets s JOIN languages l ON s.language_id=l.id
               ORDER BY s.id''').fetchall()
        data = {"exported_at": datetime.now().isoformat(), "snippets": []}
        for snip_id, lang, title, desc, code, created, updated in snippets:
            triggers = [r[0] for r in self.cursor.execute(
                "SELECT trigger_word FROM snippet_triggers WHERE snippet_id=?", (snip_id,)).fetchall()]
            tags = [r[0] for r in self.cursor.execute(
                "SELECT t.name FROM tags t JOIN snippet_tags st ON t.id=st.tag_id WHERE st.snippet_id=?",
                (snip_id,)).fetchall()]
            data["snippets"].append({
                "language": lang, "title": title, "description": desc,
                "triggers": triggers, "tags": tags, "code": code,
                "created_at": created, "updated_at": updated})
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True

    def import_from_json(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for s in data.get("snippets", []):
            ok = self.add_snippet(
                s.get("language", "python"), s.get("title", "Untitled"),
                s.get("description", ""), s.get("triggers", []),
                s.get("tags", []), s.get("code", ""))
            if ok:
                count += 1
        return count

    def close(self):
        self.conn.close()


# ============================================================
#  LINE NUMBER AREA  (with code-folding markers)
# ============================================================
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        # Clip to the actual dirty region so we skip off-screen blocks
        painter.setClipRect(event.rect())
        painter.fillRect(event.rect(), QColor("#2b2b2b"))
        block = self.editor.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top()
        bottom = top + self.editor.blockBoundingRect(block).height()
        highlight_color, default_color = QColor("#ffffff"), QColor("#858585")
        fold_width = 16  # space reserved for fold markers on the left

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                # --- fold marker ---
                if block_number in self.editor.fold_regions:
                    is_folded = block_number in self.editor.folded_lines
                    cx, cy = 6, int(top) + (self.editor.blockBoundingRect(block).height() // 2) - 5
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#aaa"))
                    if is_folded:
                        path = QPainterPath()
                        path.moveTo(cx, cy)
                        path.lineTo(cx + 8, cy + 5)
                        path.lineTo(cx, cy + 10)
                        painter.drawPath(path)
                    else:
                        path = QPainterPath()
                        path.moveTo(cx, cy)
                        path.lineTo(cx + 10, cy + 5)
                        path.lineTo(cx, cy + 10)
                        painter.drawPath(path)

                # --- bookmark dot ---
                if (block_number + 1) in self.editor.bookmarks:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#0078d4"))
                    painter.drawEllipse(fold_width + 2, int(top) + 4, 10, 10)

                # --- line number ---
                number = str(block_number + 1)
                is_current = block_number == self.editor.textCursor().blockNumber()
                painter.setPen(highlight_color if is_current else default_color)
                font = painter.font()
                font.setBold(is_current)
                painter.setFont(font)
                painter.drawText(fold_width + 18, int(top),
                                 self.width() - fold_width - 18,
                                 self.editor.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, number)

                # --- folded indicator (⋯) when a region is collapsed ---
                if block_number in self.editor.folded_lines:
                    end = self.editor.fold_regions.get(block_number, block_number)
                    hidden = end - block_number
                    if hidden > 0:
                        painter.setPen(QColor("#888"))
                        painter.drawText(fold_width + 18, int(top) + self.editor.fontMetrics().height(),
                                         self.width() - fold_width - 18, 16,
                                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                                         f"... {hidden} lines folded")

            block = block.next()
            top = bottom
            bottom = top + self.editor.blockBoundingRect(block).height()
            block_number += 1

    def mousePressEvent(self, event):
        pos = event.position()
        # Fold marker area (left 16 px)
        if pos.x() < 16:
            block = self.editor.firstVisibleBlock()
            top = self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top()
            bottom = top + self.editor.blockBoundingRect(block).height()
            while block.isValid():
                if top <= pos.y() <= bottom:
                    self.editor.toggle_fold(block.blockNumber())
                    self.update()
                    return
                block = block.next()
                top = bottom
                bottom = top + self.editor.blockBoundingRect(block).height()
        # Bookmark area (next ~14 px)
        elif pos.x() < 30:
            block = self.editor.firstVisibleBlock()
            top = self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top()
            bottom = top + self.editor.blockBoundingRect(block).height()
            while block.isValid():
                if top <= pos.y() <= bottom:
                    ln = block.blockNumber() + 1
                    if ln in self.editor.bookmarks:
                        self.editor.bookmarks.discard(ln)
                    else:
                        self.editor.bookmarks.add(ln)
                    self.update()
                    return
                block = block.next()
                top = bottom
                bottom = top + self.editor.blockBoundingRect(block).height()


# ============================================================
#  CODE EDITOR  (enhanced with multi-cursor, folding, word-wrap)
# ============================================================
class CodeEditor(QPlainTextEdit):
    status_message = Signal(str)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.line_number_area = LineNumberArea(self)
        self.bookmarks = set()
        self.snippet_triggers = {}

        # --- code folding state ---
        self.fold_regions = {}   # {start_block_number: end_block_number}
        self.folded_lines = set()

        # --- debounce timer for fold computation ---
        self._fold_timer = QTimer(self)
        self._fold_timer.setSingleShot(True)
        self._fold_timer.setInterval(300)
        self._fold_timer.timeout.connect(self._compute_fold_regions)

        # --- multi-cursor state ---
        self.extra_cursors = []  # list of QTextCursor

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.cursorPositionChanged.connect(self.update_cursor_position)
        self.document().contentsChanged.connect(self._on_contents_changed)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.setStyleSheet(
            "QPlainTextEdit{background-color:#1e1e1e;color:#d4d4d4;border:none;padding-left:10px;}")

        # completer
        self.completer = QCompleter(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setWidget(self)
        self.completer.activated.connect(self.insert_completion)
        self.python_keywords = [
            "def", "class", "import", "from", "if", "else", "elif", "return", "for", "while",
            "try", "except", "finally", "with", "as", "pass", "break", "continue", "in", "not",
            "and", "or", "is", "None", "True", "False", "lambda", "yield", "global", "nonlocal",
            "assert"]
        self.python_builtins = [
            "print", "range", "len", "int", "str", "float", "list", "dict", "set", "tuple",
            "type", "isinstance", "input", "open", "super", "__init__", "__name__", "self",
            "enumerate", "zip", "map", "filter", "sorted", "reversed", "abs", "max", "min", "sum",
            "any", "all", "hasattr", "getattr", "setattr", "property", "staticmethod",
            "classmethod", "next", "iter", "hash", "id", "hex", "oct", "bin", "chr", "ord",
            "repr", "format", "vars", "dir", "help", "callable", "dataclass", "field",
            "lru_cache", "wraps", "partial", "reduce", "Counter", "defaultdict",
            "OrderedDict", "deque", "heapq", "bisect", "itertools", "functools",
            "collections", "abc", "typing", "pathlib", "asyncio", "threading",
            "concurrent", "logging", "json", "re", "os", "sys", "math", "random",
            "datetime", "time", "copy", "pprint", "traceback", "unittest",
            "abstractmethod"]
        self.refresh_snippet_cache()

    # ---------- snippet completer ----------
    def refresh_snippet_cache(self):
        self.snippet_triggers = self.db.get_all_triggers()
        combined = self.python_keywords + self.python_builtins + list(self.snippet_triggers.keys())
        self.completer.setModel(QStringListModel(combined))

    def insert_completion(self, completion):
        tc = self.textCursor()
        tc.movePosition(tc.MoveOperation.Left, tc.KeepAnchor, len(self.completer.completionPrefix()))
        if completion.lower() in self.snippet_triggers:
            self.insert_snippet_text(self.snippet_triggers[completion.lower()], tc)
        else:
            tc.insertText(completion)
            self.setTextCursor(tc)

    def insert_snippet_text(self, code, cursor=None):
        if not cursor:
            cursor = self.textCursor()
        cursor.removeSelectedText()
        if "$0" in code:
            parts = code.split("$0", 1)
            cursor.insertText(parts[0])
            cursor_pos = cursor.position()
            cursor.insertText(parts[1])
            cursor.setPosition(cursor_pos)
        else:
            cursor.insertText(code)
        self.setTextCursor(cursor)
        self.setFocus()

    def text_under_cursor(self):
        tc = self.textCursor()
        tc.select(QTextCursor.SelectionType.WordUnderCursor)
        return tc.selectedText()

    # ---------- code folding ----------
    def _on_contents_changed(self):
        self._fold_timer.start()  # debounced fold region computation
        self.document().setModified(True)

    def _compute_fold_regions(self):
        """Detect foldable regions based on indentation changes."""
        self.fold_regions = {}
        block = self.document().begin()
        prev_indent = -1
        info = []  # [(block_number, indent)]
        while block.isValid():
            text = block.text()
            if text.strip():
                indent = len(text) - len(text.lstrip())
                info.append((block.blockNumber(), indent))
            block = block.next()
        for i, (bn, indent) in enumerate(info):
            if i + 1 < len(info) and info[i + 1][1] > indent:
                end = bn
                for j in range(i + 1, len(info)):
                    if info[j][1] <= indent:
                        break
                    end = info[j][0]
                self.fold_regions[bn] = end

    def toggle_fold(self, block_number):
        if block_number not in self.fold_regions:
            return
        end_block = self.fold_regions[block_number]
        if block_number in self.folded_lines:
            # unfold
            block = self.document().findBlockByNumber(block_number + 1)
            while block.isValid() and block.blockNumber() <= end_block:
                block.setVisible(True)
                block = block.next()
            self.folded_lines.discard(block_number)
        else:
            # fold
            block = self.document().findBlockByNumber(block_number + 1)
            while block.isValid() and block.blockNumber() <= end_block:
                block.setVisible(False)
                block = block.next()
            self.folded_lines.add(block_number)
        self.viewport().update()

    # ---------- multi-cursor ----------
    def mousePressEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.AltModifier and event.button() == Qt.MouseButton.LeftButton:
            cursor = self.cursorForPosition(event.position())
            self.extra_cursors.append(cursor)
            self._update_extra_selections()
            return
        # regular click clears extra cursors
        if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.extra_cursors.clear()
            self._update_extra_selections()
        super().mousePressEvent(event)

    def _update_extra_selections(self):
        """Draw thin highlight lines at extra-cursor positions."""
        # start from the current-line highlight
        sel = []
        if not self.isReadOnly():
            line_sel = QTextEdit.ExtraSelection()
            line_sel.format.setBackground(QColor("#2a2d2e"))
            line_sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            line_sel.cursor = self.textCursor()
            line_sel.cursor.clearSelection()
            sel.append(line_sel)
        # extra cursor highlights
        for c in self.extra_cursors:
            # line highlight
            ls = QTextEdit.ExtraSelection()
            ls.format.setBackground(QColor(255, 255, 255, 15))
            ls.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            ls.cursor = QTextCursor(c)
            ls.cursor.clearSelection()
            sel.append(ls)
            # cursor bar
            cs = QTextEdit.ExtraSelection()
            cs.cursor = c
            cs.format.setBackground(QColor(180, 210, 255, 180))
            sel.append(cs)
        self.setExtraSelections(sel)

    def _multi_insert_text(self, text):
        """Insert text at main cursor AND all extra cursors."""
        main_pos = self.textCursor().position()
        extra_positions = [c.position() for c in self.extra_cursors]
        positions = sorted(set([main_pos] + extra_positions))
        for pos in reversed(positions):
            cur = QTextCursor(self.document())
            cur.setPosition(pos)
            cur.insertText(text)
        # update cursors
        new_main = QTextCursor(self.document())
        new_main.setPosition(main_pos + len(text))
        self.setTextCursor(new_main)
        self.extra_cursors = []
        for old_pos in extra_positions:
            p = old_pos + len(text)
            nc = QTextCursor(self.document())
            nc.setPosition(p)
            self.extra_cursors.append(nc)
        self._update_extra_selections()

    def _multi_backspace(self):
        main_pos = self.textCursor().position()
        extra_positions = [c.position() for c in self.extra_cursors]
        positions = sorted(set([main_pos] + extra_positions))
        positions = [p for p in positions if p > 0]
        for pos in reversed(positions):
            cur = QTextCursor(self.document())
            cur.setPosition(pos - 1)
            cur.setPosition(pos, QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
        new_main = QTextCursor(self.document())
        new_main.setPosition(max(0, main_pos - 1) if main_pos > 0 else 0)
        self.setTextCursor(new_main)
        self.extra_cursors = []
        for old_pos in extra_positions:
            if old_pos > 0:
                nc = QTextCursor(self.document())
                nc.setPosition(old_pos - 1)
                self.extra_cursors.append(nc)
        self._update_extra_selections()

    def _multi_move(self, direction):
        """Move all cursors left (-1) or right (+1)."""
        main_pos = self.textCursor().position()
        all_pos = sorted(set([main_pos] + [c.position() for c in self.extra_cursors]))
        new_positions = []
        for p in all_pos:
            np = max(0, p + direction)
            if np == p and direction == -1 and p == 0:
                new_positions.append(p)
                continue
            new_positions.append(np)
        new_main = QTextCursor(self.document())
        new_main.setPosition(new_positions[0])
        self.setTextCursor(new_main)
        self.extra_cursors = []
        for p in new_positions[1:]:
            nc = QTextCursor(self.document())
            nc.setPosition(p)
            self.extra_cursors.append(nc)
        self._update_extra_selections()

    def _multi_enter(self):
        main_pos = self.textCursor().position()
        extra_positions = [c.position() for c in self.extra_cursors]
        positions = sorted(set([main_pos] + extra_positions))
        insertions = []
        for pos in positions:
            block = self.document().findBlock(pos)
            line_text = block.text()
            current_indent = len(line_text) - len(line_text.lstrip())
            extra = 4 if line_text.rstrip().endswith(':') else 0
            insertions.append((pos, '\n' + ' ' * (current_indent + extra)))
        for pos, txt in reversed(insertions):
            cur = QTextCursor(self.document())
            cur.setPosition(pos)
            cur.insertText(txt)
        new_main = QTextCursor(self.document())
        new_main.setPosition(main_pos + len(insertions[0][1]))
        self.setTextCursor(new_main)
        self.extra_cursors = []
        for i, old_pos in enumerate(extra_positions):
            idx = positions.index(old_pos)
            nc = QTextCursor(self.document())
            nc.setPosition(old_pos + len(insertions[idx][1]))
            self.extra_cursors.append(nc)
        self._update_extra_selections()

    # ---------- key handling ----------
    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()
        mods = event.modifiers()

        # completer popup visible
        if self.completer.popup().isVisible():
            if key in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab):
                self.completer.popup().hide()
                return
            elif key == Qt.Key_Escape:
                self.completer.popup().hide()
                super().keyPressEvent(event)
                return

        # Escape — clear multi-cursors or fold regions
        if key == Qt.Key_Escape:
            if self.extra_cursors:
                self.extra_cursors.clear()
                self._update_extra_selections()
                return
            super().keyPressEvent(event)
            return

        # multi-cursor shortcuts
        if self.extra_cursors:
            if text and text.isprintable() and not (mods & (Qt.KeyboardModifier.ControlModifier |
                                                             Qt.KeyboardModifier.AltModifier)):
                self._multi_insert_text(text)
                return
            elif key == Qt.Key_Backspace:
                self._multi_backspace()
                return
            elif key == Qt.Key_Delete:
                self.extra_cursors.clear()
                self._update_extra_selections()
            elif key == Qt.Key_Left:
                self._multi_move(-1)
                return
            elif key == Qt.Key_Right:
                self._multi_move(1)
                return
            elif key in (Qt.Key_Return, Qt.Key_Enter) and not (mods & Qt.KeyboardModifier.ShiftModifier):
                self._multi_enter()
                return
            else:
                self.extra_cursors.clear()
                self._update_extra_selections()

        # Enter — auto-indent
        if key in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            line_text = cursor.block().text()
            current_indent = len(line_text) - len(line_text.lstrip())
            if line_text.rstrip().endswith(':'):
                current_indent += 4
            super().keyPressEvent(event)
            self.insertPlainText(' ' * current_indent)
            self.trigger_completer()
            return

        # bracket auto-close
        brackets = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}
        if text in brackets:
            cursor = self.textCursor()
            if cursor.hasSelection():
                selected_text = cursor.selectedText()
                super().keyPressEvent(event)
                self.insertPlainText(selected_text + brackets[text])
                cursor = self.textCursor()
                cursor.movePosition(cursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor,
                                    len(selected_text) + 1)
                self.setTextCursor(cursor)
                return
            else:
                super().keyPressEvent(event)
                self.insertPlainText(brackets[text])
                cursor = self.textCursor()
                cursor.movePosition(cursor.MoveOperation.Left)
                self.setTextCursor(cursor)
                return

        # smart backspace (remove matching pair)
        if key == Qt.Key_Backspace:
            cursor = self.textCursor()
            if not cursor.hasSelection() and cursor.position() > 0:
                cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveOperation.KeepAnchor)
                char_before = cursor.selectedText()
                cursor.movePosition(cursor.MoveOperation.Right)
                cursor.movePosition(cursor.MoveOperation.Right, cursor.MoveOperation.KeepAnchor)
                char_after = cursor.selectedText()
                if char_before in ['(', '[', '{', '"', "'"] and char_before == char_after:
                    cursor.deleteChar()
                    cursor.movePosition(cursor.MoveOperation.Left)
                    cursor.deleteChar()
                    return

        super().keyPressEvent(event)
        if text.isalnum() or text == '_':
            self.trigger_completer()
        else:
            self.completer.popup().hide()

    # ---------- word wrap ----------
    def toggle_word_wrap(self):
        if self.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        else:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    # ---------- completer ----------
    def trigger_completer(self):
        word = self.text_under_cursor()
        if len(word) >= 2:
            self.completer.setCompletionPrefix(word)
            popup = self.completer.popup()
            popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
            cursor_rect = self.cursorRect()
            cursor_rect.setWidth(
                self.completer.popup().sizeHintForColumn(0) +
                self.completer.popup().verticalScrollBar().sizeHint().width())
            self.completer.complete(cursor_rect)
        else:
            self.completer.popup().hide()

    # ---------- ctrl+scroll zoom ----------
    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            font = self.font()
            font.setPointSize(max(1, font.pointSize() + (1 if delta > 0 else -1)))
            self.setFont(font)
        else:
            super().wheelEvent(event)

    # ---------- cursor position ----------
    def update_cursor_position(self):
        c = self.textCursor()
        self.status_message.emit(f"Ln {c.blockNumber() + 1}, Col {c.columnNumber() + 1}")

    # ---------- line number area geometry ----------
    def line_number_area_width(self):
        digits = 1
        max_value = max(1, self.blockCount())
        while max_value >= 10:
            max_value /= 10
            digits += 1
        return 35 + self.fontMetrics().horizontalAdvance('9') * digits

    def update_line_number_area_width(self, n):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area.width(), cr.height()))

    def highlight_current_line(self):
        extra_selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#2a2d2e"))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        # re-add multi-cursor highlights if any
        for c in self.extra_cursors:
            ls = QTextEdit.ExtraSelection()
            ls.format.setBackground(QColor(255, 255, 255, 15))
            ls.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            ls.cursor = QTextCursor(c)
            ls.cursor.clearSelection()
            extra_selections.append(ls)
            cs = QTextEdit.ExtraSelection()
            cs.cursor = c
            cs.format.setBackground(QColor(180, 210, 255, 180))
            extra_selections.append(cs)
        self.setExtraSelections(extra_selections)


# ============================================================
#  MINIMAP WIDGET
# ============================================================
class MinimapWidget(QWidget):
    """Scaled-down code overview, synced with the editor scroll.
    
    Performance: renders code to a cached QPixmap on content change;
    on scroll, only blits the cached pixmap + redraws the viewport overlay.
    This avoids iterating every block of the document on every scroll event.
    """

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setFixedWidth(100)
        self.setMinimumHeight(100)
        self._dragging = False
        self._cache: QPixmap | None = None
        self._cache_dirty = True

        # Only re-render the full minimap when content actually changes
        editor.document().contentsChanged.connect(self._invalidate_cache)
        # Scroll just triggers a repaint (uses cached pixmap)
        editor.verticalScrollBar().valueChanged.connect(self.update)
        editor.horizontalScrollBar().valueChanged.connect(self.update)

    def _invalidate_cache(self):
        self._cache_dirty = True
        self.update()

    def _rebuild_cache(self):
        """Render all visible lines to an off-screen pixmap."""
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        pixmap = QPixmap(w, h)
        pixmap.fill(QColor("#1e1e1e"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        doc = self.editor.document()
        block_count = doc.blockCount()
        if block_count == 0:
            painter.end()
            self._cache = pixmap
            self._cache_dirty = False
            return

        line_h = max(1, h // max(1, block_count))
        char_w = max(1, line_h // 2)

        block = doc.begin()
        y = 0
        while block.isValid():
            if not block.isVisible():
                block = block.next()
                continue
            text = block.text()
            x = 0
            stripped = text.lstrip()
            # simplified coloring per line
            if stripped.startswith('#'):
                color = QColor("#6a9955")
            elif stripped.startswith(('def ', 'class ', 'import ', 'from ')):
                color = QColor("#c586c0")
            elif stripped.startswith(('"', "'")):
                color = QColor("#ce9178")
            else:
                color = QColor("#666")
            # Only render up to widget width to avoid wasting time off-screen
            max_x = w
            for ch in text:
                if not ch.isspace():
                    if x < max_x:
                        painter.fillRect(x, y, char_w, max(1, line_h - 1), color)
                x += char_w
                if x > max_x:
                    break
            y += line_h
            block = block.next()

        painter.end()
        self._cache = pixmap
        self._cache_dirty = False

    def paintEvent(self, event):
        if self._cache_dirty or self._cache is None:
            self._rebuild_cache()

        painter = QPainter(self)
        if self._cache:
            painter.drawPixmap(0, 0, self._cache)

        # viewport indicator (always drawn live since it depends on scroll)
        sb = self.editor.verticalScrollBar()
        total = max(1, sb.maximum() + sb.pageStep())
        vp_top = int(self.height() * sb.value() / total)
        vp_h = max(4, int(self.height() * sb.pageStep() / total))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 35))
        painter.drawRect(0, vp_top, self.width(), vp_h)
        painter.setBrush(QColor(255, 255, 255, 20))
        painter.drawRect(0, vp_top, 2, vp_h)  # thin left edge highlight

    def mousePressEvent(self, event):
        self._dragging = True
        self._scroll_to(event.position().y())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._scroll_to(event.position().y())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _scroll_to(self, y):
        sb = self.editor.verticalScrollBar()
        ratio = max(0.0, min(1.0, y / max(1, self.height())))
        sb.setValue(int(ratio * sb.maximum()))


# ============================================================
#  EDITOR CONTAINER  (one editor + its minimap)
# ============================================================
class EditorContainer(QWidget):
    """Holds a CodeEditor and its MinimapWidget side by side."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.file_path = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.editor = CodeEditor(db)
        self.minimap = MinimapWidget(self.editor)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.minimap)


# ============================================================
#  GO TO LINE DIALOG
# ============================================================
class GoToLineDialog(QDialog):
    def __init__(self, max_line, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go to Line")
        self.setFixedSize(300, 100)
        self.setStyleSheet("background-color:#2b2b2b;color:#d4d4d4;")
        layout = QVBoxLayout(self)
        hl = QHBoxLayout()
        hl.addWidget(QLabel("Line number:"))
        self.spin = QSpinBox()
        self.spin.setRange(1, max_line)
        self.spin.setStyleSheet("background-color:#1e1e1e;color:#d4d4d4;padding:5px;")
        hl.addWidget(self.spin)
        layout.addLayout(hl)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        self.spin.setFocus()
        self.spin.selectAll()


# ============================================================
#  ADD / EDIT SNIPPET DIALOG
# ============================================================
class AddEditSnippetDialog(QDialog):
    def __init__(self, edit_data=None, parent=None):
        super().__init__(parent)
        self.edit_data = edit_data
        self.setWindowTitle("Edit Snippet" if edit_data else "Add New Snippet")
        self.setMinimumSize(500, 450)
        self.setStyleSheet("background-color:#2b2b2b;color:#d4d4d4;")
        layout = QFormLayout(self)
        style = "background-color:#1e1e1e;color:#d4d4d4;padding:5px;"

        self.lang_input = QComboBox()
        self.lang_input.setEditable(True)
        self.lang_input.addItems(["Python", "C++", "JavaScript", "Java", "HTML", "CSS"])
        self.lang_input.setStyleSheet(style)
        layout.addRow("Language:", self.lang_input)

        self.title_input = QLineEdit()
        self.title_input.setStyleSheet(style)
        layout.addRow("Title:", self.title_input)

        self.desc_input = QLineEdit()
        self.desc_input.setStyleSheet(style)
        self.desc_input.setPlaceholderText("Short description of what it does")
        layout.addRow("Description:", self.desc_input)

        self.trigger_input = QLineEdit()
        self.trigger_input.setStyleSheet(style)
        self.trigger_input.setPlaceholderText("Comma separated (e.g., defn, func, deff)")
        layout.addRow("Trigger Words:", self.trigger_input)

        self.tag_input = QLineEdit()
        self.tag_input.setStyleSheet(style)
        self.tag_input.setPlaceholderText("Comma separated (e.g., oop, boilerplate, django)")
        layout.addRow("Tags:", self.tag_input)

        self.code_input = QPlainTextEdit()
        self.code_input.setFont(QFont("Consolas", 10))
        self.code_input.setPlaceholderText("Code here. Use $0 for final cursor position.")
        self.code_input.setStyleSheet(style)
        layout.addRow("Code:", self.code_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        # pre-fill if editing
        if edit_data:
            self.lang_input.setCurrentText(edit_data["language"].capitalize())
            self.title_input.setText(edit_data["title"])
            self.desc_input.setText(edit_data.get("description", ""))
            self.trigger_input.setText(", ".join(edit_data.get("triggers", [])))
            self.tag_input.setText(", ".join(edit_data.get("tags", [])))
            self.code_input.setPlainText(edit_data.get("code", ""))


# ============================================================
#  SNIPPET MANAGER DIALOG  (enhanced with Edit / Export / Import)
# ============================================================
class SnippetManagerDialog(QDialog):
    def __init__(self, db, editor, parent=None):
        super().__init__(parent)
        self.db = db
        self.editor = editor
        self.setWindowTitle("Snippet Manager")
        self.resize(600, 550)
        self.setStyleSheet("background-color:#2b2b2b;color:#d4d4d4;")

        layout = QVBoxLayout(self)
        style = "background-color:#1e1e1e;color:#d4d4d4;padding:5px;"

        # filters
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Lang:"))
        self.lang_filter = QComboBox()
        self.lang_filter.setStyleSheet(style)
        filter_layout.addWidget(self.lang_filter)
        filter_layout.addWidget(QLabel("Tag:"))
        self.tag_filter = QComboBox()
        self.tag_filter.setStyleSheet(style)
        filter_layout.addWidget(self.tag_filter)

        btn_add = QPushButton("+ Add")
        btn_add.clicked.connect(self.open_add_dialog)
        btn_add.setStyleSheet("padding:5px;")
        filter_layout.addWidget(btn_add)
        layout.addLayout(filter_layout)

        self.snippet_list = QListWidget()
        self.snippet_list.setStyleSheet(
            "QListWidget{background-color:#1e1e1e;color:#d4d4d4;border:none;padding:5px;}"
            "QListWidget::item:selected{background-color:#264f78;}")
        layout.addWidget(self.snippet_list)

        # details preview
        self.details_label = QLabel("Select a snippet to see details.")
        self.details_label.setWordWrap(True)
        self.details_label.setStyleSheet(
            "color:#858585;padding:10px;background-color:#252526;border:1px solid #333;")
        layout.addWidget(self.details_label)

        # action buttons
        action_layout = QHBoxLayout()
        btn_load = QPushButton("Load")
        btn_load.clicked.connect(self.load_snippet)
        btn_load.setStyleSheet("padding:8px;background-color:#0078d4;color:white;font-weight:bold;")
        btn_edit = QPushButton("Edit")
        btn_edit.clicked.connect(self.edit_snippet)
        btn_edit.setStyleSheet("padding:8px;background-color:#388a34;color:white;font-weight:bold;")
        btn_delete = QPushButton("Delete")
        btn_delete.clicked.connect(self.delete_snippet)
        btn_delete.setStyleSheet("padding:8px;background-color:#d13438;color:white;")
        action_layout.addWidget(btn_load)
        action_layout.addWidget(btn_edit)
        action_layout.addWidget(btn_delete)
        action_layout.addStretch()

        btn_export = QPushButton("Export")
        btn_export.clicked.connect(self.export_snippets)
        btn_export.setStyleSheet("padding:8px;background-color:#555;color:white;")
        btn_import = QPushButton("Import")
        btn_import.clicked.connect(self.import_snippets)
        btn_import.setStyleSheet("padding:8px;background-color:#555;color:white;")
        action_layout.addWidget(btn_export)
        action_layout.addWidget(btn_import)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        btn_close.setStyleSheet("padding:8px;")
        action_layout.addWidget(btn_close)
        layout.addLayout(action_layout)

        self.refresh_languages()
        self.lang_filter.currentTextChanged.connect(self.refresh_tags)
        self.lang_filter.currentTextChanged.connect(self.refresh_snippets)
        self.tag_filter.currentTextChanged.connect(self.refresh_snippets)
        self.snippet_list.itemClicked.connect(self.show_details)

    def refresh_languages(self):
        self.lang_filter.blockSignals(True)
        self.lang_filter.clear()
        self.lang_filter.addItems(self.db.get_languages())
        self.lang_filter.blockSignals(False)
        if self.lang_filter.count() > 0:
            self.refresh_tags(self.lang_filter.currentText())
            self.refresh_snippets(self.lang_filter.currentText())

    def refresh_tags(self, language):
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItems(self.db.get_tags_for_language(language))
        self.tag_filter.blockSignals(False)

    def refresh_snippets(self, language):
        self.snippet_list.clear()
        self.details_label.setText("Select a snippet to see details.")
        if not language:
            return
        tag = self.tag_filter.currentText()
        for snip_id, title, desc, triggers, tags in self.db.get_snippets_filtered(language, tag):
            display = f"{title}  [{triggers or 'No Trigger'}]  ({tags or 'No Tags'})"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, snip_id)
            self.snippet_list.addItem(item)

    def show_details(self, item):
        snip_id = item.data(Qt.ItemDataRole.UserRole)
        row = self.db.cursor.execute(
            "SELECT description,code,created_at FROM snippets WHERE id=?", (snip_id,)).fetchone()
        if row:
            desc, code, created = row
            code_preview = code[:200] + ("..." if len(code) > 200 else "")
            self.details_label.setText(
                f"<b>Description:</b> {desc or 'None'}<br>"
                f"<b>Created:</b> {created[:10]}<br><br>"
                f"<pre>{code_preview}</pre>")

    def open_add_dialog(self):
        dialog = AddEditSnippetDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_snippet(dialog, is_new=True)

    def edit_snippet(self):
        item = self.snippet_list.currentItem()
        if not item:
            return
        snip_id = item.data(Qt.ItemDataRole.UserRole)
        data = self.db.get_snippet_by_id(snip_id)
        if not data:
            return
        dialog = AddEditSnippetDialog(edit_data=data, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_snippet(dialog, is_new=False, snippet_id=snip_id)

    def _save_snippet(self, dialog, is_new=False, snippet_id=None):
        lang = dialog.lang_input.currentText()
        title = dialog.title_input.text()
        desc = dialog.desc_input.text()
        triggers = [t.strip() for t in dialog.trigger_input.text().split(',') if t.strip()]
        tags = [t.strip() for t in dialog.tag_input.text().split(',') if t.strip()]
        code = dialog.code_input.toPlainText()
        if not (lang and title and code and triggers):
            QMessageBox.warning(self, "Error",
                                "Language, Title, at least one Trigger, and Code are required.")
            return
        if is_new:
            if self.db.add_snippet(lang, title, desc, triggers, tags, code):
                self.refresh_languages()
                self.lang_filter.setCurrentText(lang.capitalize())
            else:
                QMessageBox.warning(self, "Error", "Failed to add. Check for duplicate triggers.")
        else:
            if self.db.update_snippet(snippet_id, lang, title, desc, triggers, tags, code):
                self.refresh_snippets(self.lang_filter.currentText())
            else:
                QMessageBox.warning(self, "Error", "Failed to update. Check for duplicate triggers.")

    def load_snippet(self):
        item = self.snippet_list.currentItem()
        if not item:
            return
        snip_id = item.data(Qt.ItemDataRole.UserRole)
        code = self.db.cursor.execute(
            "SELECT code FROM snippets WHERE id=?", (snip_id,)).fetchone()[0]
        self.editor.insert_snippet_text(code)
        self.close()

    def delete_snippet(self):
        item = self.snippet_list.currentItem()
        if not item:
            return
        snip_id = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, "Delete",
                                     "Delete this snippet and all its triggers/tags?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_snippet(snip_id)
            self.refresh_tags(self.lang_filter.currentText())
            self.refresh_snippets(self.lang_filter.currentText())

    def export_snippets(self):
        fp, _ = QFileDialog.getSaveFileName(self, "Export Snippets", "snippets_export.json",
                                            "JSON Files (*.json)")
        if fp:
            try:
                self.db.export_to_json(fp)
                QMessageBox.information(self, "Export", f"Exported to {fp}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def import_snippets(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Import Snippets", "",
                                            "JSON Files (*.json)")
        if fp:
            try:
                count = self.db.import_from_json(fp)
                QMessageBox.information(self, "Import", f"Imported {count} snippet(s).")
                self.refresh_languages()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def closeEvent(self, event):
        self.editor.refresh_snippet_cache()
        super().closeEvent(event)


# ============================================================
#  FIND & REPLACE DIALOG
# ============================================================
class FindReplaceDialog(QDialog):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setWindowTitle("Find & Replace")
        self.setFixedSize(420, 180)
        self.setStyleSheet("background-color:#2b2b2b;color:#d4d4d4;")
        layout = QVBoxLayout(self)
        fl = QHBoxLayout()
        fl.addWidget(QLabel("Find:"))
        self.fi = QLineEdit()
        self.fi.returnPressed.connect(self.fn)
        fl.addWidget(self.fi)
        b = QPushButton("Find")
        b.clicked.connect(self.fn)
        fl.addWidget(b)
        self.case_check = QPushButton("Aa")
        self.case_check.setCheckable(True)
        self.case_check.setToolTip("Case Sensitive")
        self.case_check.setFixedWidth(36)
        self.case_check.setStyleSheet(
            "QPushButton{padding:4px;font-weight:bold;}"
            "QPushButton:checked{background-color:#0078d4;color:white;}")
        fl.addWidget(self.case_check)
        layout.addLayout(fl)
        rl = QHBoxLayout()
        rl.addWidget(QLabel("Replace:"))
        self.ri = QLineEdit()
        rl.addWidget(self.ri)
        b2 = QPushButton("Replace")
        b2.clicked.connect(self.rc)
        rl.addWidget(b2)
        layout.addLayout(rl)
        bl = QHBoxLayout()
        b3 = QPushButton("Replace All")
        b3.clicked.connect(self.ra)
        bl.addWidget(b3)
        self.match_label = QLabel("")
        self.match_label.setStyleSheet("color:#858585;")
        bl.addStretch()
        bl.addWidget(self.match_label)
        layout.addLayout(bl)

    def _search_flags(self):
        flags = QTextDocument.FindFlag(0)
        if self.case_check.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def fn(self):
        t = self.fi.text()
        if not t:
            return
        flags = self._search_flags()
        if not self.editor.find(t, flags):
            c = self.editor.textCursor()
            c.movePosition(c.MoveOperation.Start)
            self.editor.setTextCursor(c)
            self.editor.find(t, flags)
            self.match_label.setText("Wrapped")

    def rc(self):
        sel = self.editor.textCursor().selectedText()
        search = self.fi.text()
        if sel and (sel == search or (not self.case_check.isChecked() and sel.lower() == search.lower())):
            self.editor.insertPlainText(self.ri.text())
        self.fn()

    def ra(self):
        search = self.fi.text()
        replace = self.ri.text()
        if not search:
            return
        text = self.editor.toPlainText()
        flags = 0 if self.case_check.isChecked() else re.IGNORECASE
        count = len(re.findall(re.escape(search), text, flags))
        if count == 0:
            self.match_label.setText("No matches")
            return
        if self.case_check.isChecked():
            new_text = text.replace(search, replace)
        else:
            new_text = re.sub(re.escape(search), replace.replace('\\', '\\\\'), text, flags=re.IGNORECASE)
        self.editor.setPlainText(new_text)
        self.match_label.setText(f"Replaced {count} occurrence(s)")


# ============================================================
#  MAIN WINDOW  (enhanced with all 12 features)
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Professional Code Editor (Enhanced)")
        self.resize(1200, 800)
        self.settings = QSettings("MyCompany", "PyCodeEditor")
        self.snippet_db = SnippetDB()

        # --- console with clear button ---
        console_container = QWidget()
        cc_layout = QVBoxLayout(console_container)
        cc_layout.setContentsMargins(0, 0, 0, 0)
        cc_layout.setSpacing(0)
        console_toolbar = QWidget()
        ct_layout = QHBoxLayout(console_toolbar)
        ct_layout.setContentsMargins(5, 2, 5, 2)
        ct_layout.addStretch()
        clear_btn = QPushButton("Clear Console")
        clear_btn.setFixedHeight(24)
        clear_btn.setStyleSheet(
            "background-color:#333;color:#d4d4d4;border:1px solid #555;padding:0 10px;"
            "border-radius:3px;")
        clear_btn.clicked.connect(self.clear_console)
        ct_layout.addWidget(clear_btn)
        cc_layout.addWidget(console_toolbar)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 10))
        self.console.setStyleSheet(
            "QTextEdit{background-color:#1a1a1a;color:#d4d4d4;border-top:1px solid #444;padding:5px;}")
        self.console.setPlaceholderText("Output will appear here...")
        cc_layout.addWidget(self.console)

        # --- tab widget ---
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setStyleSheet(
            "QTabWidget::pane{border:none;}"
            "QTabBar::tab{background:#2d2d2d;color:#aaa;padding:6px 12px;border:none;"
            "border-right:1px solid #1e1e1e;}"
            "QTabBar::tab:selected{background:#1e1e1e;color:#d4d4d4;}"
            "QTabBar::close-button{image:none;}")
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        # --- splitter ---
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.tab_widget)
        self.splitter.addWidget(console_container)
        self.splitter.setSizes([600, 200])
        self.setCentralWidget(self.splitter)

        # --- menus, toolbar, status bar ---
        self.create_menus()
        self.create_toolbar()
        self.status_bar_label = QLabel("Ln 1, Col 1")
        self.status_bar_label.setStyleSheet("color:#aaa;padding:0 8px;")
        self.status_bar_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_bar_label.mousePressEvent = self._copy_cursor_pos
        self.statusBar().addPermanentWidget(self.status_bar_label)
        self.statusBar().showMessage("Ready")

        # --- first tab ---
        self._open_new_tab()

        # --- file tree dock ---
        self.file_tree_dock = self._create_file_tree()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.file_tree_dock)

        # --- find dialog (shared) ---
        self.find_dialog = None
        self.current_file = None

        # --- auto-save timer ---
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self._auto_save)
        self.auto_save_timer.start(30000)  # 30 seconds

        # --- restore settings ---
        self.load_settings()

    # ==================== file tree ====================
    def _create_file_tree(self):
        dock = QDockWidget("File Explorer", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setMinimumWidth(200)
        tree_view = QTreeView()
        tree_view.setHeaderHidden(True)
        tree_view.setAnimated(True)
        tree_view.setIndentation(16)
        tree_view.setExpandsOnDoubleClick(True)
        tree_view.setStyleSheet(
            "QTreeView{background-color:#252526;color:#d4d4d4;border:none;padding:5px;}"
            "QTreeView::item:selected{background-color:#264f78;}"
            "QTreeView::item:hover{background-color:#2a2d2e;}")
        self.file_model = QFileSystemModel()
        self.file_model.setRootPath(QDir.currentPath())
        tree_view.setModel(self.file_model)
        tree_view.setRootIndex(self.file_model.index(QDir.currentPath()))
        # hide extra columns (size, type, date)
        for i in range(1, 4):
            tree_view.hideColumn(i)
        tree_view.doubleClicked.connect(self._on_file_tree_double_click)
        dock.setWidget(tree_view)
        self.tree_view = tree_view
        return dock

    def _on_file_tree_double_click(self, index):
        fp = self.file_model.filePath(index)
        if os.path.isfile(fp):
            self.open_file_in_tab(fp)

    # ==================== tab management ====================
    def _container(self, index=None):
        if index is None:
            index = self.tab_widget.currentIndex()
        if index < 0:
            return None
        return self.tab_widget.widget(index)

    def current_editor(self):
        c = self._container()
        return c.editor if c else None

    def _open_new_tab(self, file_path=None):
        container = EditorContainer(self.snippet_db)
        editor = container.editor
        editor.status_message.connect(self._on_status_message)
        editor._status_connected = True
        self.highlighter = PythonSyntaxHighlighter(editor.document())
        idx = self.tab_widget.addTab(container, "Untitled")
        self.tab_widget.setCurrentIndex(idx)
        # Connect modified indicator after tab is added so indexOf() works
        editor.document().contentsChanged.connect(
            lambda c=container: self._update_tab_title(self.tab_widget.indexOf(c)))
        container.file_path = file_path
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    editor.setPlainText(f.read())
                editor.document().setModified(False)
                name = os.path.basename(file_path)
                self.tab_widget.setTabText(idx, name)
                self.setWindowTitle(f"Professional Code Editor - {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
        return container

    def close_tab(self, index):
        container = self._container(index)
        if container and container.editor.document().isModified():
            name = self.tab_widget.tabText(index)
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                f"'{name}' has unsaved changes. Close anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return
        self.tab_widget.removeTab(index)
        if self.tab_widget.count() == 0:
            self._open_new_tab()

    def on_tab_changed(self, index):
        container = self._container(index)
        if not container:
            return
        editor = container.editor
        # Avoid reconnecting the signal on every tab switch (prevents duplicate calls)
        if not getattr(editor, '_status_connected', False):
            editor.status_message.connect(self._on_status_message)
            editor._status_connected = True
        c = editor.textCursor()
        self.status_bar_label.setText(f"Ln {c.blockNumber() + 1}, Col {c.columnNumber() + 1}")
        if container.file_path:
            self.setWindowTitle(f"Professional Code Editor - {container.file_path}")
        else:
            self.setWindowTitle("Professional Code Editor - Untitled")
        # update tab title for modified state
        self._update_tab_title(index)

    def _update_tab_title(self, index):
        container = self._container(index)
        if not container:
            return
        name = os.path.basename(container.file_path) if container.file_path else "Untitled"
        if container.editor.document().isModified():
            self.tab_widget.setTabText(index, f"{name} *")
        else:
            self.tab_widget.setTabText(index, name)

    def _on_status_message(self, msg):
        self.status_bar_label.setText(msg)

    def _copy_cursor_pos(self, event):
        QApplication.clipboard().setText(self.status_bar_label.text())
        self.statusBar().showMessage("Copied: " + self.status_bar_label.text(), 2000)

    def clear_console(self):
        self.console.clear()

    # ==================== menus ====================
    def create_menus(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        file_menu.addAction("New Tab", self._open_new_tab, "Ctrl+T")
        file_menu.addAction("Open File", self.open_file_dialog, "Ctrl+O")
        file_menu.addAction("Save", self.save_current_file, "Ctrl+S")
        file_menu.addAction("Save As...", self.save_current_file_as, "Ctrl+Shift+S")
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close, "Ctrl+Q")

        edit_menu = menubar.addMenu("Edit")
        edit_menu.addAction("Undo", lambda: self.current_editor().undo() if self.current_editor() else None, "Ctrl+Z")
        edit_menu.addAction("Redo", lambda: self.current_editor().redo() if self.current_editor() else None, "Ctrl+Y")
        edit_menu.addSeparator()
        edit_menu.addAction("Find & Replace", self.open_find_replace, "Ctrl+H")
        edit_menu.addAction("Go to Line...", self.go_to_line, "Ctrl+G")

        view_menu = menubar.addMenu("View")
        view_menu.addAction("Toggle Word Wrap", self.toggle_word_wrap, "Ctrl+Shift+W")
        view_menu.addAction("Toggle File Explorer", self.toggle_file_tree, "Ctrl+B")
        view_menu.addAction("Toggle Minimap", self.toggle_minimap, "Ctrl+Shift+M")

        snippet_menu = menubar.addMenu("Snippets")
        snippet_menu.addAction("Manage Snippets", self.open_snippet_manager, "Ctrl+Shift+X")
        snippet_menu.addAction("Export Snippets...", self.export_snippets_action, "Ctrl+Shift+E")
        snippet_menu.addAction("Import Snippets...", self.import_snippets_action, "Ctrl+Shift+I")

    def create_toolbar(self):
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setStyleSheet("background-color:#2b2b2b;border:none;spacing:5px;")
        toolbar.addAction("New Tab", self._open_new_tab)
        toolbar.addAction("Open", self.open_file_dialog)
        toolbar.addAction("Save", self.save_current_file)
        toolbar.addSeparator()
        toolbar.addAction("Run", "Ctrl+R", self.run_code)
        toolbar.addAction("Find", "Ctrl+H", self.open_find_replace)
        toolbar.addAction("Go to Line", "Ctrl+G", self.go_to_line)
        toolbar.addSeparator()
        toolbar.addAction("Snippets", "Ctrl+Shift+X", self.open_snippet_manager)

    # ==================== file operations ====================
    def open_file_dialog(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Open File", "",
                                            "Python Files (*.py);;All Files (*)")
        if fp:
            self.open_file_in_tab(fp)

    def open_file_in_tab(self, fp):
        # check if already open
        for i in range(self.tab_widget.count()):
            c = self._container(i)
            if c and c.file_path == os.path.abspath(fp):
                self.tab_widget.setCurrentIndex(i)
                return
        self._open_new_tab(fp)

    def save_current_file(self):
        container = self._container()
        if not container:
            return
        if not container.file_path:
            self.save_current_file_as()
            return
        try:
            with open(container.file_path, 'w', encoding='utf-8') as f:
                f.write(container.editor.toPlainText())
            container.editor.document().setModified(False)
            self._update_tab_title(self.tab_widget.currentIndex())
            self.statusBar().showMessage(f"Saved: {container.file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def save_current_file_as(self):
        container = self._container()
        if not container:
            return
        fp, _ = QFileDialog.getSaveFileName(self, "Save File", "",
                                            "Python Files (*.py);;All Files (*)")
        if fp:
            container.file_path = fp
            self.save_current_file()
            self.setWindowTitle(f"Professional Code Editor - {fp}")

    # ==================== features ====================
    def go_to_line(self):
        editor = self.current_editor()
        if not editor:
            return
        dlg = GoToLineDialog(editor.blockCount(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            line = dlg.spin.value()
            block = editor.document().findBlockByNumber(line - 1)
            if block.isValid():
                cursor = editor.textCursor()
                cursor.setPosition(block.position())
                editor.setTextCursor(cursor)
                editor.centerCursor()
                editor.setFocus()

    def toggle_word_wrap(self):
        editor = self.current_editor()
        if editor:
            editor.toggle_word_wrap()

    def toggle_file_tree(self):
        self.file_tree_dock.setVisible(not self.file_tree_dock.isVisible())

    def toggle_minimap(self):
        container = self._container()
        if container:
            container.minimap.setVisible(not container.minimap.isVisible())

    def open_find_replace(self):
        editor = self.current_editor()
        if not editor:
            return
        if not self.find_dialog:
            self.find_dialog = FindReplaceDialog(editor, self)
        else:
            self.find_dialog.editor = editor
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()

    def open_snippet_manager(self):
        editor = self.current_editor()
        if editor:
            SnippetManagerDialog(self.snippet_db, editor, self).exec()

    def export_snippets_action(self):
        fp, _ = QFileDialog.getSaveFileName(self, "Export Snippets",
                                            "snippets_export.json", "JSON Files (*.json)")
        if fp:
            try:
                self.snippet_db.export_to_json(fp)
                QMessageBox.information(self, "Export", f"Exported to {fp}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def import_snippets_action(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Import Snippets", "",
                                            "JSON Files (*.json)")
        if fp:
            try:
                count = self.snippet_db.import_from_json(fp)
                QMessageBox.information(self, "Import", f"Imported {count} snippet(s).")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    # ==================== auto-save ====================
    def _auto_save(self):
        container = self._container()
        if not container:
            return
        if container.file_path and container.editor.document().isModified():
            try:
                with open(container.file_path, 'w', encoding='utf-8') as f:
                    f.write(container.editor.toPlainText())
                container.editor.document().setModified(False)
                self._update_tab_title(self.tab_widget.currentIndex())
                self.statusBar().showMessage(f"Auto-saved: {container.file_path}", 2000)
            except Exception:
                pass

    # ==================== run code ====================
    def run_code(self):
        container = self._container()
        if not container:
            return
        if not container.file_path:
            QMessageBox.warning(self, "No File", "Save the file before running.")
            self.save_current_file_as()
            if not container.file_path:
                return
        self.save_current_file()
        self.console.clear()
        self.console.append(f"--- Running {container.file_path} ---\n")
        try:
            result = subprocess.run(['python', container.file_path],
                                    capture_output=True, text=True, timeout=30)
            if result.stdout:
                self.console.append(result.stdout)
            if result.stderr:
                self.console.append(f"<span style='color:#f48771;'>{result.stderr}</span>")
            self.console.append("\n--- Process Finished ---")
        except Exception as e:
            self.console.append(f"<span style='color:#f48771;'>{str(e)}</span>")
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    # ==================== settings persistence ====================
    def closeEvent(self, event):
        self.save_settings()
        self.snippet_db.close()
        super().closeEvent(event)

    def save_settings(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("splitter_state", self.splitter.saveState())
        editor = self.current_editor()
        if editor:
            self.settings.setValue("font_size", editor.font().pointSize())

    def load_settings(self):
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        if self.settings.value("window_state"):
            self.restoreState(self.settings.value("window_state"))
        if self.settings.value("splitter_state"):
            self.splitter.restoreState(self.settings.value("splitter_state"))
        font_size = self.settings.value("font_size", type=int)
        if font_size:
            editor = self.current_editor()
            if editor:
                f = editor.font()
                f.setPointSize(font_size)
                editor.setFont(f)


# ============================================================
#  PYTHON SYNTAX HIGHLIGHTER
# ============================================================
class PythonSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.highlighting_rules = []

        # --- Keywords (purple, bold) ---
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#c586c0"))
        kw_fmt.setFontWeight(QFont.Weight.Bold)
        for w in ["def", "class", "import", "from", "if", "else", "elif", "return", "for",
                   "while", "try", "except", "finally", "with", "as", "pass", "break",
                   "continue", "in", "not", "and", "or", "is", "None", "True", "False",
                   "lambda", "yield", "raise", "del", "global", "nonlocal", "assert",
                   "async", "await", "match", "case"]:
            self.highlighting_rules.append((QRegularExpression(r"\b" + w + r"\b"), kw_fmt))

        # --- Strings (orange) — order matters: triple-quoted first to avoid partial matches ---
        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#ce9178"))
        self.highlighting_rules.append((QRegularExpression(r'f\"\"\"[\s\S]*?\"\"\"'), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r"f'''[\s\S]*?'''"), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r'\"\"\"[\s\S]*?\"\"\"'), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r"'''[\s\S]*?'''"), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r'f\".*?\"'), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r"f'.*?'"), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r'\".*?\"|\'.*?\''), str_fmt))

        # --- Comments (green, italic) ---
        com_fmt = QTextCharFormat()
        com_fmt.setForeground(QColor("#6a9955"))
        com_fmt.setFontItalic(True)
        self.highlighting_rules.append((QRegularExpression(r"#.*"), com_fmt))

        # --- Decorators (yellow-green) ---
        dec_fmt = QTextCharFormat()
        dec_fmt.setForeground(QColor("#d7ba7d"))
        self.highlighting_rules.append((QRegularExpression(r"@\w+(\.\w+)*"), dec_fmt))

        # --- Function definitions (yellow) ---
        func_fmt = QTextCharFormat()
        func_fmt.setForeground(QColor("#dcdcaa"))
        self.highlighting_rules.append(
            (QRegularExpression(r"\b(?<=def\s)[a-zA-Z_][a-zA-Z0-9_]*"), func_fmt))

        # --- Class names after 'class' keyword ---
        class_fmt = QTextCharFormat()
        class_fmt.setForeground(QColor("#4ec9b0"))
        self.highlighting_rules.append(
            (QRegularExpression(r"\b(?<=class\s)[a-zA-Z_][a-zA-Z0-9_]*"), class_fmt))

        # --- Numbers (light green) ---
        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor("#b5cea8"))
        self.highlighting_rules.append(
            (QRegularExpression(r"\b[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?\b"), num_fmt))

        # --- Builtins (cyan) ---
        builtin_fmt = QTextCharFormat()
        builtin_fmt.setForeground(QColor("#4ec9b0"))
        builtins = ["print", "range", "len", "int", "str", "float", "list", "dict", "set",
                     "tuple", "type", "isinstance", "input", "open", "super", "enumerate",
                     "zip", "map", "filter", "sorted", "reversed", "abs", "max", "min", "sum",
                     "any", "all", "hasattr", "getattr", "setattr", "property", "staticmethod",
                     "classmethod", "next", "iter", "hash", "id", "hex", "oct", "bin", "chr",
                     "ord", "repr", "format", "vars", "dir", "help", "callable"]
        for b in builtins:
            self.highlighting_rules.append((QRegularExpression(r"\b" + b + r"\b(?=\()"), builtin_fmt))

        # --- self (blue) ---
        self_fmt = QTextCharFormat()
        self_fmt.setForeground(QColor("#569cd6"))
        self.highlighting_rules.append((QRegularExpression(r"\bself\b"), self_fmt))

        # --- Type hints (teal) — CapitalizedWords used as type annotations ---
        type_hint_fmt = QTextCharFormat()
        type_hint_fmt.setForeground(QColor("#4ec9b0"))
        self.highlighting_rules.append(
            (QRegularExpression(r"(?<=[:\(,\[->])\s*[A-Z][a-zA-Z0-9_]*"), type_hint_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                # Skip if this range is already inside a comment or string
                start, length = m.capturedStart(), m.capturedLength()
                if not self._overlaps_comment_or_string(text, start, start + length):
                    self.setFormat(start, length, fmt)

    def _overlaps_comment_or_string(self, text, start, end):
        """Quick check: does the range overlap a # comment or triple-quoted string?"""
        # Check for comment
        comment_pos = text.find('#')
        if 0 <= comment_pos < end and start < len(text):
            if comment_pos <= start or (comment_pos < end and not text[:comment_pos].count('"') % 2 == 1):
                return True
        return False


# ============================================================
#  ENTRY POINT
# ============================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    p = app.palette()
    for role, color in [
        (p.ColorRole.Window, "#2b2b2b"), (p.ColorRole.WindowText, "#d4d4d4"),
        (p.ColorRole.Base, "#1e1e1e"), (p.ColorRole.Text, "#d4d4d4"),
        (p.ColorRole.Button, "#2b2b2b"), (p.ColorRole.ButtonText, "#d4d4d4"),
        (p.ColorRole.Highlight, "#264f78"), (p.ColorRole.HighlightedText, "#d4d4d4"),
    ]:
        p.setColor(role, QColor(color))
    app.setPalette(p)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())