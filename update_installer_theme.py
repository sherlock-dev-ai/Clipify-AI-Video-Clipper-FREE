import re

path = r'L:\ClipifyAI\android\app\src\main\assets\www\installer\index.html'
with open(path, 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update root variables
html = html.replace('--bg: #090e0c;', '--bg: #090a0d;')
html = html.replace('--surface: #121a16;', '--surface: #111318;')
html = html.replace('--surface-card: #16221c;', '--surface-card: #161922;')
html = html.replace('--surface-active: #1c2e25;', '--surface-active: #212530;')
html = html.replace('--border: rgba(16, 185, 129, 0.2);', '--border: rgba(255, 255, 255, 0.12);')
html = html.replace('--border-active: #10b981;', '--border-active: #ffffff;')
html = html.replace('--primary: #10b981;', '--primary: #ffffff;')
html = html.replace('--primary-dark: #059669;', '--primary-dark: #e2e8f0;')
html = html.replace('--primary-gradient: linear-gradient(135deg, #10b981 0%, #047857 100%);', '--primary-gradient: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);')

# 2. Update brand glow & badges
html = html.replace('box-shadow: 0 0 10px rgba(16, 185, 129, 0.3);', 'box-shadow: 0 0 10px rgba(255, 255, 255, 0.2);')

# Header platform badge
html = re.sub(r'Android\s+v[0-9.]+', 'Android v5.0.1', html)

# Brand badge styling
html = re.sub(
    r'(\.brand-badge\s*\{[^}]*?background:\s*)rgba\(16,\s*185,\s*129,\s*0\.15\);[^}]*?border:\s*1px\s+solid\s+rgba\(16,\s*185,\s*129,\s*0\.35\);[^}]*?color:\s*#34d399;',
    r'\1rgba(255, 255, 255, 0.08);\n      border: 1px solid rgba(255, 255, 255, 0.18);\n      color: #ffffff;',
    html,
    flags=re.DOTALL
)

# Step number color
html = re.sub(
    r'(\.step-num\s*\{[^}]*?color:\s*)#34d399;',
    r'\1#ffffff;',
    html
)

# Option card selected shadow
html = html.replace('box-shadow: 0 0 16px rgba(16, 185, 129, 0.15);', 'box-shadow: 0 0 16px rgba(255, 255, 255, 0.08);')

# Option badge
html = re.sub(
    r'(\.option-badge\s*\{[^}]*?background:\s*)rgba\(16,\s*185,\s*129,\s*0\.18\);[^}]*?color:\s*#34d399;',
    r'\1rgba(255, 255, 255, 0.1);\n      color: #ffffff;\n      border: 1px solid rgba(255, 255, 255, 0.16);',
    html,
    flags=re.DOTALL
)

# Check icon
html = re.sub(
    r'(\.check-icon\s*\{[^}]*?background:\s*)rgba\(16,\s*185,\s*129,\s*0\.16\);[^}]*?color:\s*#34d399;',
    r'\1rgba(255, 255, 255, 0.1);\n      color: #ffffff;\n      border: 1px solid rgba(255, 255, 255, 0.2);',
    html,
    flags=re.DOTALL
)

# Terminal dots & logs
html = html.replace('.dot-green { background: #10b981; }', '.dot-green { background: #ffffff; box-shadow: 0 0 6px rgba(255, 255, 255, 0.6); }')
html = html.replace('.log-success { color: #34d399; }', '.log-success { color: #ffffff; font-weight: 500; }')

# Primary button styling
html = re.sub(
    r'(\.btn-primary\s*\{[^}]*?)background:\s*var\(--primary-gradient\);[^}]*?color:\s*#ffffff;[^}]*?box-shadow:\s*0\s+4px\s+14px\s+rgba\(16,\s*185,\s*129,\s*0\.35\);',
    r'\1background: #ffffff;\n      color: #090a0d;\n      border: 1px solid #ffffff;\n      font-weight: 600;\n      box-shadow: 0 4px 14px rgba(255, 255, 255, 0.15);',
    html,
    flags=re.DOTALL
)

# Star button small
html = re.sub(
    r'(\.btn-star-small\s*\{[^}]*?background:\s*)rgba\(16,\s*185,\s*129,\s*0\.15\);[^}]*?border:\s*1px\s+solid\s+rgba\(16,\s*185,\s*129,\s*0\.35\);[^}]*?color:\s*#34d399;',
    r'\1rgba(255, 255, 255, 0.1);\n      border: 1px solid rgba(255, 255, 255, 0.25);\n      color: #ffffff;',
    html,
    flags=re.DOTALL
)

# Any remaining inline green colors
html = html.replace('style="color: #34d399;"', 'style="color: #ffffff; background: rgba(255, 255, 255, 0.1);"')
html = html.replace('style="color: #34d399; font-size: 1.15rem;"', 'style="color: #ffffff; font-size: 1.15rem;"')

# Device Verification dynamic elements
html = re.sub(
    r'<strong>Xiaomi\s+15T\s+Pro\s+\(arm64-v8a\)</strong>\s*<div[^>]*?>12\.0\s+GB\s+RAM[^<]*?</div>',
    '<strong id="device-model-label">Detecting device...</strong>\n              <div id="device-ram-label" style="font-size: 0.75rem; color: var(--text-dim);">Analyzing hardware capabilities...</div>',
    html
)

# Terminal device command
html = re.sub(
    r'<div class="log-cmd">\$ clipify-init --device xiaomi-15t-pro --arch arm64-v8a</div>',
    '<div class="log-cmd" id="terminal-device-cmd">$ clipify-init --device mobile --arch arm64-v8a</div>',
    html
)

# Add populateDeviceInfo function in script
js_code = '''
    function populateDeviceInfo() {
      let info = null;
      try {
        if (window.AndroidBridge && window.AndroidBridge.getDeviceInfoJson) {
          const raw = window.AndroidBridge.getDeviceInfoJson();
          if (raw && typeof raw === 'string') {
            info = JSON.parse(raw);
          }
        }
      } catch (e) {
        console.warn('Error reading AndroidBridge device info:', e);
      }

      const modelEl = document.getElementById('device-model-label');
      const ramEl = document.getElementById('device-ram-label');
      const cmdEl = document.getElementById('terminal-device-cmd');

      if (info && (info.deviceName || info.model)) {
        const name = info.deviceName || `${info.brand || ''} ${info.model || ''}`.trim() || 'Android Device';
        const arch = info.arch || 'arm64-v8a';
        const ram = info.totalRamGb ? `${info.totalRamGb} GB RAM` : 'Optimized Memory';
        const os = info.androidVer ? ` · ${info.androidVer}` : '';

        if (modelEl) modelEl.textContent = `${name} (${arch})`;
        if (ramEl) ramEl.textContent = `${ram} · Hardware Acceleration Ready${os}`;
        if (cmdEl) {
          const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-');
          cmdEl.textContent = `$ clipify-init --device ${slug} --arch ${arch}`;
        }
      } else {
        const ua = navigator.userAgent;
        let name = 'Android Mobile';
        let arch = 'arm64-v8a';
        const match = ua.match(/Android\\s+([0-9.]+);\\s*([^;)]+)/);
        if (match && match[2]) {
          name = match[2].trim();
        }
        if (modelEl) modelEl.textContent = `${name} (${arch})`;
        if (ramEl) ramEl.textContent = 'Hardware Acceleration Ready · MediaCodec Active';
        if (cmdEl) {
          const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-');
          cmdEl.textContent = `$ clipify-init --device ${slug} --arch ${arch}`;
        }
      }
    }
    window.addEventListener('DOMContentLoaded', populateDeviceInfo);
    setTimeout(populateDeviceInfo, 50);
    setTimeout(populateDeviceInfo, 300);
'''

if 'populateDeviceInfo' not in html:
    html = html.replace('function showStep(step) {', js_code + '\n    function showStep(step) {\n      populateDeviceInfo();')

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)
print('Updated installer/index.html successfully!')

