/*
 * ClawSafe Pay — Shared Theme Loader
 * Reads theme from localStorage and applies it to <html>.
 * Also provides a floating theme picker for non-dashboard pages.
 */
(function(){
  var saved = localStorage.getItem('clawsafe-theme') || 'midnight';
  document.documentElement.setAttribute('data-theme', saved);

  /* Inject a small floating theme picker on non-dashboard pages */
  document.addEventListener('DOMContentLoaded', function(){
    if (document.getElementById('themeMenu')) return; /* dashboard has its own */

    var themes = [
      {id:'midnight',label:'Midnight',color:'#05080f'},
      {id:'slate',label:'Slate',color:'#1a1d23'},
      {id:'ocean',label:'Ocean',color:'#0c1929'},
      {id:'cloud',label:'Cloud',color:'#f0f4f8'},
      {id:'sand',label:'Sand',color:'#f5f0e8'},
      {id:'mint',label:'Mint',color:'#ecfdf5'},
      {id:'carbon',label:'Carbon',color:'#000'},
      {id:'graphite',label:'Graphite',color:'#17181a'},
      {id:'ember',label:'Ember',color:'#100604'},
      {id:'sakura',label:'Sakura',color:'#fdf2f5'}
    ];

    var wrap = document.createElement('div');
    wrap.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999';

    var btn = document.createElement('button');
    btn.textContent = '🎨';
    btn.title = 'Change Theme';
    btn.style.cssText = 'width:40px;height:40px;border-radius:50%;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:18px;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.3);transition:all .2s;backdrop-filter:blur(12px)';
    btn.onmouseenter = function(){ btn.style.transform = 'scale(1.1)'; };
    btn.onmouseleave = function(){ btn.style.transform = 'scale(1)'; };

    var menu = document.createElement('div');
    menu.style.cssText = 'display:none;position:absolute;bottom:48px;right:0;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:8px;min-width:150px;backdrop-filter:blur(16px);box-shadow:0 12px 40px rgba(0,0,0,.35)';

    var title = document.createElement('div');
    title.textContent = 'Theme';
    title.style.cssText = 'font-size:9px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:6px;padding:0 4px;font-weight:600';
    menu.appendChild(title);

    themes.forEach(function(t){
      var opt = document.createElement('button');
      opt.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:6px;cursor:pointer;font-size:11px;color:var(--text);background:none;border:none;width:100%;text-align:left;font-family:inherit;transition:background .15s';
      opt.onmouseenter = function(){ opt.style.background = 'var(--surface-hover,rgba(99,102,241,.06))'; };
      opt.onmouseleave = function(){ opt.style.background = 'none'; };

      var swatch = document.createElement('span');
      swatch.style.cssText = 'width:14px;height:14px;border-radius:4px;border:1.5px solid rgba(128,128,128,.25);flex-shrink:0;background:' + t.color;
      opt.appendChild(swatch);
      opt.appendChild(document.createTextNode(t.label));

      opt.addEventListener('click', function(){
        document.documentElement.setAttribute('data-theme', t.id);
        localStorage.setItem('clawsafe-theme', t.id);
        menu.style.display = 'none';
      });
      menu.appendChild(opt);
    });

    btn.addEventListener('click', function(e){
      e.stopPropagation();
      menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
    });
    document.addEventListener('click', function(){ menu.style.display = 'none'; });

    wrap.appendChild(menu);
    wrap.appendChild(btn);
    document.body.appendChild(wrap);
  });
})();
