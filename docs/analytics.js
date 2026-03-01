// Analytics loader — single source of truth for all tracking
// To swap providers: edit this file only. No page rebuilds needed.
(function() {
  // Load GoatCounter
  var s = document.createElement('script');
  s.setAttribute('data-goatcounter', 'https://augmentedmike.goatcounter.com/count');
  s.setAttribute('async', '');
  s.src = '//gc.zgo.at/count.js';
  document.head.appendChild(s);

  // Wait for GoatCounter to be ready, then wire up events
  function trackEvents() {
    if (typeof window.goatcounter === 'undefined' || !window.goatcounter.count) {
      return setTimeout(trackEvents, 250);
    }

    // Tip jar clicks
    document.querySelectorAll('a[href*="buy.stripe.com"], a[href*="stripe.com"], .tip-jar, [data-tip]').forEach(function(el) {
      el.addEventListener('click', function() {
        window.goatcounter.count({ path: 'tip-jar-click', title: 'Tip Jar', event: true });
      });
    });

    // Outbound link clicks
    document.querySelectorAll('a[href^="http"]').forEach(function(el) {
      var href = el.getAttribute('href') || '';
      if (href.indexOf(location.hostname) !== -1) return; // skip internal
      el.addEventListener('click', function() {
        window.goatcounter.count({
          path: 'outbound/' + href.replace(/^https?:\/\//, '').split('/')[0],
          title: 'Outbound: ' + (el.textContent || href).trim().slice(0, 60),
          event: true
        });
      });
    });

    // Language switcher (EN/ES toggle)
    document.querySelectorAll('[data-lang], .lang-toggle, #lang-btn').forEach(function(el) {
      el.addEventListener('click', function() {
        var lang = el.getAttribute('data-lang') || el.textContent || 'unknown';
        window.goatcounter.count({ path: 'lang-switch/' + lang.trim(), title: 'Language Switch', event: true });
      });
    });
  }

  // Wire up after DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', trackEvents);
  } else {
    trackEvents();
  }
})();
