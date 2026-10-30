/* Live filters — a form with data-live-filter narrows its list as you type.
 *
 * Typing in a text or search input runs 250 ms after the last keystroke; any
 * other control runs at once; submitting (Enter) runs at once too. The query
 * is written into the address bar so a filtered list can be bookmarked, and
 * re-fetched with ?partial=1 so only the results fragment comes back. Without
 * JavaScript the form is an ordinary GET form.
 */

const FILTER_DEBOUNCE_MS = 250;

const JackilFilters = {
  bind(form) {
    //: Per form, so two live filters on one page can't stamp on each other.
    let seq = 0;
    let applied = 0;
    let timer = null;
    let controller = null;

    const run = () => {
      const params = new URLSearchParams(new FormData(form));
      for (const key of [...params.keys()]) {
        if (!params.get(key)) params.delete(key);
      }
      const qs = params.toString();
      history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));

      //: Saved-view forms post the current query along; keep theirs in step.
      document.querySelectorAll('input[data-live-query]').forEach((input) => {
        input.value = qs;
      });

      params.set('partial', '1');
      const mine = ++seq;
      //: Abort whatever this form still has in flight: the newest filter wins.
      if (controller) controller.abort();
      controller = new AbortController();
      fetch(location.pathname + '?' + params.toString(), {
        credentials: 'same-origin',
        signal: controller.signal,
      })
        .then((response) => {
          if (!response.ok) return null;
          return response.text();
        })
        .then((html) => {
          if (html === null || mine < applied) return;
          applied = mine;

          const doc = document.createElement('template');
          doc.innerHTML = html;
          const fresh = doc.content.querySelector('[data-live-results]');
          if (!fresh) return;

          document.querySelectorAll('[data-live-results]').forEach((old) => {
            old.replaceWith(fresh.cloneNode(true));
          });
          const shown = document.querySelector('[data-live-results]');
          if (shown && shown.hasAttribute('data-count-label')) {
            document.querySelectorAll('[data-live-count]').forEach((count) => {
              count.textContent = shown.getAttribute('data-count-label');
            });
          }
          document.dispatchEvent(
            new CustomEvent('jackil:live-updated', { detail: { root: fresh } }),
          );
        })
        .catch(() => {
          //: A failed or aborted fetch leaves the current results as they are.
        });
    };

    form.addEventListener('input', (event) => {
      const type = (event.target.type || '').toLowerCase();
      if (!['text', 'search'].includes(type)) return;
      clearTimeout(timer);
      timer = setTimeout(run, FILTER_DEBOUNCE_MS);
    });

    form.addEventListener('change', (event) => {
      const type = (event.target.type || '').toLowerCase();
      if (['text', 'search'].includes(type)) return;
      clearTimeout(timer);
      run();
    });

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      clearTimeout(timer);
      run();
    });
  },

  init() {
    document.querySelectorAll('form[data-live-filter]').forEach((form) => {
      this.bind(form);
    });
  },
};

JackilFilters.init();
