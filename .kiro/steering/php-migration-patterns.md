---
inclusion: fileMatch
fileMatchPattern: "*.php,*.tpl,*.phtml,fixer.py,patterns.yaml"
---

# PHP Migration Error Patterns and Fixes

## Common PHP 8+ Migration Issues

### 1. Undefined Array Key Errors
**Problem**: PHP 8+ throws warnings for undefined array keys
**Pattern**: `Undefined array key "key_name"`
**Fix Strategy**: Use null coalescing operator (??)

```php
// Before (causes warning)
$value = $_GET['param'];
$data = $array['key'];

// After (safe)
$value = $_GET['param'] ?? null;
$data = $array['key'] ?? null;
```

### 2. Dynamic Property Deprecations
**Problem**: PHP 8.2+ deprecates dynamic properties on classes
**Pattern**: `Creation of dynamic property Class::$property is deprecated`
**Fix Strategy**: Declare properties or use #[AllowDynamicProperties]

```php
// Option 1: Declare properties
class MyClass {
    public $dynamicProperty; // Declare explicitly
}

// Option 2: Allow dynamic properties (less preferred)
#[AllowDynamicProperties]
class MyClass {
    // Properties can be created dynamically
}
```

### 3. Null Parameter Warnings
**Problem**: Functions expecting non-null parameters receive null
**Pattern**: `Passing null to parameter #1 ($string) of type string is deprecated`
**Fix Strategy**: Cast or provide defaults

```php
// Before
htmlspecialchars($value);
strlen($text);

// After
htmlspecialchars((string)($value ?? ''));
strlen($text ?? '');
```

### 4. Deprecated Function Usage
**Problem**: Old functions removed in PHP 8+
**Common Cases**:
- `ereg()` → `preg_match()`
- `split()` → `explode()`
- `each()` → `foreach`
- `create_function()` → anonymous functions

## Error Detection Strategies

### Pattern Matching Rules
1. **File Path Extraction**: Look for `in /path/to/file.php on line 123`
2. **Error Type Classification**: Fatal > Warning > Notice > Deprecated
3. **Context Analysis**: Consider surrounding code for better fixes
4. **Style Preservation**: Maintain existing indentation and formatting

### Fix Application Order
1. **Rule-based fixes** - Apply patterns.yaml rules first
2. **Dynamic property declarations** - Add missing property declarations
3. **AI-powered fixes** - Use LLM for complex cases
4. **Syntax validation** - Verify PHP syntax after changes

## Style Inference Guidelines

### Detect Project Conventions
- **Indentation**: Tabs vs spaces, 2/4/8 space width
- **Brace Style**: Same line vs next line
- **Quote Preference**: Single vs double quotes
- **Array Syntax**: `[]` vs `array()`
- **Echo Style**: `<?= ?>` vs `echo`

### Preserve Existing Style
```php
// If project uses tabs and same-line braces
if ($condition) {
    $array = ['key' => 'value'];
}

// If project uses spaces and next-line braces
if ($condition)
{
    $array = array('key' => 'value');
}
```

## Testing Approach

### Validation Steps
1. **PHP Lint Check**: `php -l file.php` after changes
2. **Backup Creation**: Always create .bak files
3. **Idempotent Testing**: Ensure fixes can run multiple times safely
4. **Context Preservation**: Don't break unrelated functionality

### Error Categorization
- **Critical**: Fatal errors, class not found, syntax errors
- **High**: Undefined functions, method calls on null
- **Medium**: Undefined variables, array key warnings
- **Low**: Deprecated notices, strict standards

## AI Prompt Guidelines

When using AI for complex fixes:
1. Provide file context and error details
2. Specify coding style preferences
3. Request minimal, surgical changes only
4. Ask for explanation of changes made
5. Validate output before applying

## Common Pitfalls to Avoid

1. **Over-fixing**: Don't change unrelated code
2. **Style Breaking**: Maintain project conventions
3. **Logic Changes**: Preserve original behavior
4. **Security Issues**: Don't introduce vulnerabilities
5. **Performance Impact**: Avoid unnecessary overhead

## Pattern Development Process

1. **Identify Error**: Collect real error messages
2. **Create Pattern**: Write regex to match error context
3. **Design Fix**: Create minimal, safe replacement
4. **Test Thoroughly**: Validate against multiple examples
5. **Document**: Add clear notes and examples