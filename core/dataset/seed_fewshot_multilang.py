"""
Seed high-quality multilang examples for Java, C#, and JavaScript.
"""

import chromadb
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

COLLECTION = "utcoder_fewshot_examples"

EXAMPLES = [
    # JAVASCRIPT
    {
        "language": "javascript",
        "title": "JavaScript Math utility with Jest",
        "source": '''\
function add(a, b) {
    return a + b;
}

function divide(a, b) {
    if (b === 0) {
        throw new Error("Cannot divide by zero");
    }
    return a / b;
}

module.exports = { add, divide };
''',
        "test": '''\
const { add, divide } = require('module_under_test');

describe('Math utilities', () => {
    describe('add', () => {
        it('should add two positive numbers', () => {
            expect(add(2, 3)).toBe(5);
        });
        
        it('should handle negative numbers', () => {
            expect(add(-2, 5)).toBe(3);
        });
    });

    describe('divide', () => {
        it('should divide two numbers', () => {
            expect(divide(10, 2)).toBe(5);
        });

        it('should throw error when dividing by zero', () => {
            expect(() => divide(10, 0)).toThrow("Cannot divide by zero");
        });
    });
});
'''
    },
    
    # JAVA
    {
        "language": "java",
        "title": "Java Calculator with JUnit 5",
        "source": '''\
package com.example;

public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }
    
    public double divide(double a, double b) {
        if (b == 0.0) {
            throw new IllegalArgumentException("Cannot divide by zero");
        }
        return a / b;
    }
}
''',
        "test": '''\
package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CalculatorTest {

    private final Calculator calculator = new Calculator();

    @Test
    void testAdd() {
        assertEquals(5, calculator.add(2, 3), "2 + 3 should equal 5");
        assertEquals(3, calculator.add(-2, 5), "Negative numbers should add correctly");
    }

    @Test
    void testDivide() {
        assertEquals(5.0, calculator.divide(10.0, 2.0));
    }

    @Test
    void testDivideByZeroThrowsException() {
        Exception exception = assertThrows(IllegalArgumentException.class, () -> {
            calculator.divide(10.0, 0.0);
        });
        assertEquals("Cannot divide by zero", exception.getMessage());
    }
}
'''
    },

    # C#
    {
        "language": "csharp",
        "title": "C# Calculator with xUnit",
        "source": '''\
using System;

namespace Example
{
    public class Calculator
    {
        public int Add(int a, int b)
        {
            return a + b;
        }

        public double Divide(double a, double b)
        {
            if (b == 0)
            {
                throw new DivideByZeroException("Cannot divide by zero");
            }
            return a / b;
        }
    }
}
''',
        "test": '''\
using System;
using Xunit;
using Example;

namespace Example.Tests
{
    public class CalculatorTests
    {
        private readonly Calculator _calculator = new Calculator();

        [Fact]
        public void Add_ValidNumbers_ReturnsSum()
        {
            int result = _calculator.Add(2, 3);
            Assert.Equal(5, result);
        }

        [Theory]
        [InlineData(-2, 5, 3)]
        [InlineData(0, 0, 0)]
        public void Add_VariousNumbers_ReturnsExpectedSum(int a, int b, int expected)
        {
            int result = _calculator.Add(a, b);
            Assert.Equal(expected, result);
        }

        [Fact]
        public void Divide_ByZero_ThrowsDivideByZeroException()
        {
            Assert.Throws<DivideByZeroException>(() => _calculator.Divide(10, 0));
        }
    }
}
'''
    }
    ,
    # PYTHON
    {
        "language": "python",
        "title": "Python Math utility with Pytest",
        "source": '''\
def add(a, b):
    return a + b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
''',
        "test": '''\
import pytest
from module_under_test import add, divide

def test_add():
    assert add(2, 3) == 5
    assert add(-2, 5) == 3

def test_divide():
    assert divide(10, 2) == 5.0

def test_divide_by_zero():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(10, 0)
'''
    }
]

def main():
    print("Loading embedding model...")
    embeddings = OllamaEmbeddings(
        base_url="http://localhost:11434",
        model="nomic-embed-text"
    )

    print("Connecting to ChromaDB...")
    client = chromadb.PersistentClient(path="./chroma_db")
    collection = client.get_or_create_collection(name=COLLECTION)

    docs = []
    ids = []
    metadatas = []
    vectors = []

    print("Embedding examples...")
    for idx, ex in enumerate(EXAMPLES):
        content = (
            f"**Source Code:**\n```\n{ex['source']}\n```\n\n"
            f"**Correct test file:**\n```\n{ex['test']}\n```"
        )
        
        # Lean embedding (source code only)
        vector = embeddings.embed_query(ex["source"])
        
        docs.append(content)
        ids.append(f"multilang_seed_{ex['language']}_{idx}")
        metadatas.append({
            "type": "dataset_example",
            "language": ex["language"],
            "title": ex["title"]
        })
        vectors.append(vector)

    print(f"Upserting {len(docs)} documents into Chroma...")
    collection.upsert(
        ids=ids,
        embeddings=vectors,
        documents=docs,
        metadatas=metadatas
    )

    print("Done! Multi-language few-shot examples indexed.")

if __name__ == "__main__":
    main()
