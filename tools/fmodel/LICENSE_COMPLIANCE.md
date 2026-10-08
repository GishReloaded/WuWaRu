# License Compliance Summary

## ✅ All Issues Resolved

### 1. License Changed from MIT to GPL-3.0

**Why?**
- FModel (our main dependency) is licensed under **GPL-3.0**
- GPL-3.0 is a **copyleft license** - any derivative work must also use GPL-3.0
- FModelCLI directly uses FModel's code, making it a derivative work

**What Changed:**
- ✅ `LICENSE` file updated to GPL-3.0
- ✅ README.md badges and license section updated
- ✅ CONTRIBUTING.md updated
- ✅ GPL header added to `Program.cs`
- ✅ Created `NOTICE` file documenting all dependencies

### 2. Git Submodule Handling

**Correct Behavior:**
- Git submodules are **tracked** by Git via `.gitmodules`
- The `upstream/FModel` directory should **NOT** be in `.gitignore`
- Git stores only a reference (commit hash) in the parent repo
- The actual submodule content is managed separately

**What Changed:**
- ✅ Removed misleading comment from `.gitignore`
- ✅ `.gitmodules` correctly configured
- ✅ Submodule will be properly tracked

### 3. License Compatibility Matrix

| Component | License | Compatible with GPL-3.0? | Notes |
|-----------|---------|---------------------------|-------|
| **FModel** | GPL-3.0 | ✅ Yes (same license) | **Requires GPL-3.0** |
| **CUE4Parse** | Apache-2.0 | ✅ Yes | Can be used in GPL software |
| **Newtonsoft.Json** | MIT | ✅ Yes | Can be used in GPL software |
| **System.Resources.Extensions** | MIT | ✅ Yes | Can be used in GPL software |

**Conclusion:** GPL-3.0 is the correct license for this project.

## 📋 GPL-3.0 Requirements Checklist

For anyone distributing FModelCLI (including you):

- [x] **Source code availability** - Must provide source to anyone who receives binaries
- [x] **License notice** - Include GPL-3.0 license text (✅ in `LICENSE`)
- [x] **Copyright notice** - Include in source files (✅ added to `Program.cs`)
- [x] **Modification notice** - Document any changes (✅ via Git history)
- [x] **Dependency attribution** - List all third-party components (✅ in `NOTICE`)
- [x] **Same license** - Derivatives must also be GPL-3.0 (✅ documented)

## 🚀 What You Can Do

### ✅ Allowed:
- Use the software for any purpose (including commercial)
- Modify the source code
- Distribute original or modified versions
- Charge money for distribution

### ⚠️ Requirements:
- **Must** provide source code with binaries
- **Must** keep the GPL-3.0 license
- **Must** document your changes
- **Must** include copyright notices

### ❌ Prohibited:
- Cannot make it proprietary (close the source)
- Cannot relicense under MIT, Apache, etc.
- Cannot remove copyright/license notices
- Cannot sublicense (everyone gets the same GPL-3.0 rights)

## 📁 Updated File List

```
FModelCLI/
├── .gitignore              ✅ Correct (doesn't ignore submodules)
├── .gitmodules             ✅ Tracks FModel submodule
├── LICENSE                 ✅ Changed to GPL-3.0
├── NOTICE                  ✅ New - Third-party attributions
├── README.md               ✅ Updated license info
├── CONTRIBUTING.md         ✅ Updated license requirements
├── CHANGELOG.md            ✅ No changes needed
├── .github/workflows/      ✅ No changes needed
└── FModelCLI/Program.cs    ✅ Added GPL header
```

## 🎯 Before Publishing to GitHub

1. **Review all files** - Make sure you're comfortable with GPL-3.0
2. **Replace placeholders** - Change `yourusername` in README
3. **Test build** - Run `.\sync_upstream.ps1` one more time
4. **Read GPL-3.0** - Understand your obligations: https://www.gnu.org/licenses/gpl-3.0.html

## 💡 Common GPL-3.0 Questions

**Q: Can I use this in my commercial project?**
A: Yes, but your project must also be GPL-3.0 if you distribute it.

**Q: Can I sell binaries?**
A: Yes, but you must provide source code to buyers.

**Q: Can I keep my modifications private?**
A: Yes, if you don't distribute them. GPL only applies to distribution.

**Q: What if I just use it as a tool (not linking)?**
A: If you're just running `FModelCLI.exe` as a separate process, your code doesn't need to be GPL. This is how Ludiglot uses it.

## 📞 Resources

- **GPL-3.0 Full Text**: https://www.gnu.org/licenses/gpl-3.0.txt
- **GPL FAQ**: https://www.gnu.org/licenses/gpl-faq.html
- **GPL Compatibility**: https://www.gnu.org/licenses/license-compatibility.html
- **FModel License**: https://github.com/4sval/FModel/blob/master/LICENSE

---

**All license compliance issues have been resolved. The project is now ready for open source distribution under GPL-3.0.** ✅
