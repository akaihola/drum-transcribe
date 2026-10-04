// The same six connections serve compact trees and wide, sideways diagrams.
window.TrackLayout = (() => {
  const tracks = {src: 'Original', drumless: 'Without drums', drums: 'Drums stem',
    adtof: 'ADTOF', mdx23c: 'MDX23C', fused: 'Fused'};
  const mediaSelector = 'audio, yt-audio, practice-audio';
  let markerId = 0;

  function draw(grid) {
    if (!grid?.offsetWidth) return;
    const base = grid.getBoundingClientRect();
    const box = key => {
      const r = grid.querySelector(`[data-track="${key}"], [data-key="${key}"]`).getBoundingClientRect();
      return {l: r.left - base.left, r: r.right - base.left, t: r.top - base.top,
        b: r.bottom - base.top, x: r.left - base.left + r.width / 2,
        y: r.top - base.top + r.height / 2};
    };
    const links = [['src', 'drumless'], ['src', 'drums'], ['drums', 'adtof'],
      ['drums', 'mdx23c'], ['adtof', 'fused'], ['mdx23c', 'fused']];
    const sideways = box('src').r < box('drums').l;
    grid.dataset.layout = sideways ? 'sideways' : 'tree';
    grid.setAttribute('role', 'group');
    grid.setAttribute('aria-description', 'The original splits into without drums and drums stem. The drums stem feeds ADTOF and MDX23C. Both feed Fused.');
    const paths = links.map(([from, to]) => {
      const a = box(from), b = box(to);
      if (sideways) {
        const x = (a.r + b.l) / 2;
        return `M${a.r + 3} ${a.y}H${x}V${b.y}H${b.l - 5}`;
      }
      const x = Math.max(a.l + 12, Math.min(a.r - 12, b.x)), y = (a.b + b.t) / 2;
      return `M${x} ${a.b + 3}V${y}H${b.x}V${b.t - 5}`;
    });
    grid.querySelector('svg.track-arrows')?.remove();
    const id = grid.dataset.marker ||= `track-arrow-${++markerId}`;
    grid.insertAdjacentHTML('beforeend', `<svg class="track-arrows" aria-hidden="true">
      <defs><marker id="${id}" viewBox="0 0 8 8" refX="7" refY="4"
        markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L8 4 L0 8z"/></marker></defs>
      ${paths.map(d => `<path d="${d}" fill="none" stroke="currentColor" stroke-width="1.2"
        marker-end="url(#${id})"/>`).join('')}</svg>`);
  }

  function showInfo(section, key, button) {
    const piece = section.querySelector(`[data-piece="${key}"]`);
    const pop = section.querySelector('.track-info-popover') ||
      section.appendChild(Object.assign(document.createElement('div'), {className: 'popcard track-info-popover'}));
    pop.setAttribute('popover', 'auto');
    const paragraphs = [...piece.querySelectorAll('.popcard')].map(p => p.innerHTML);
    const stats = piece.querySelector('.stats')?.cloneNode(true);
    stats?.querySelectorAll('button, [popover]').forEach(e => e.remove());
    pop.innerHTML = `<b>${tracks[key]}</b>` + paragraphs.map(p => `<p>${p}</p>`).join('') +
      (stats ? `<p>${stats.textContent}</p>` : '');
    pop.showPopover();
    placeNote(pop, button);
  }

  function header() {
    if (document.documentElement.classList.contains('mobile')) return;
    if (!document.querySelector('.project-heading')) {
      const back = document.querySelector('body > p > a[href="/"]')?.parentElement;
      if (back) {
        const heading = document.createElement('header');
        heading.className = 'project-heading';
        back.before(heading);
        const tools = document.createElement('div');
        tools.className = 'project-tools';
        tools.append(document.querySelector('#gear-btn'), document.querySelector('#help-btn'));
        heading.append(back, document.querySelector('#title'), tools);
      }
    }
    const versions = document.querySelector('#app > .grouplbl');
    if (versions) document.querySelector('.vtabs > .tabbar').prepend(versions);
  }

  function decorate(section) {
    if (document.documentElement.classList.contains('mobile')) return;
    const flow = section.querySelector('.flow');
    if (!flow || section.querySelector('.track-picker')) return;
    const picker = document.createElement('div');
    picker.className = 'track-picker';
    picker.innerHTML = `<div class="track-grid" role="group" aria-label="Choose a track">
      ${Object.entries(tracks).map(([key, name]) => `<div class="track-choice"
        data-track="${key}" style="grid-area:${key}"><button type="button" class="track-select" aria-pressed="false"><b>${name}</b><small></small></button><button type="button" class="minfo track-info" aria-label="About ${name}"><span>i</span></button><button type="button" class="track-play" aria-label="Play ${name}">▶</button></div>`).join('')}
      </div><p class="track-hint">Choose a backing track. Press its triangle to play.</p>`;
    (section.recording?.supported ? section.recording.ui : flow).before(picker);
    flow.classList.add('track-details');
    const grid = picker.querySelector('.track-grid');
    const media = key => flow.querySelector(`[data-piece="${key}"]`)?.querySelector(mediaSelector);
    let shown = 'src', lastBacking, toolsContent, queued = false;

    function paint() {
      queued = false;
      const backing = flow.querySelector('practice-audio.on')?.dataset.backing;
      if (backing && backing !== lastBacking) shown = backing;
      lastBacking = backing;
      for (const button of grid.querySelectorAll('[data-track]')) {
        const key = button.dataset.track, piece = flow.querySelector(`[data-piece="${key}"]`);
        const player = media(key), control = player?.querySelector('button');
        const progress = piece?.querySelector('.prog');
        let status = player ? 'Ready' : progress?.querySelector('.act')?.textContent || 'Not available';
        if (player?.tagName === 'PRACTICE-AUDIO' && player.classList.contains('on')) {
          status = control.textContent;
          if (control.hasAttribute('data-progress')) status += ` ${control.style.getPropertyValue('--backing-progress')}`;
        } else if (player && !player.paused) status = 'Playing';
        else if (player && key === shown) status = 'Selected · Ready';
        button.querySelector('small').textContent = status;
        button.title = progress?.dataset.tip || status;
        button.querySelector('.track-select').setAttribute('aria-pressed', key === shown);
        const play = button.querySelector('.track-play');
        play.disabled = !player;
        play.textContent = player && !player.paused ? 'Ⅱ' : '▶';
        play.setAttribute('aria-label', `${player && !player.paused ? 'Pause' : 'Play'} ${tracks[key]}`);
        button.setAttribute('aria-busy', control?.getAttribute('aria-busy') === 'true');
        button.classList.toggle('working', progress?.classList.contains('running') || progress?.classList.contains('arriving'));
        button.classList.toggle('failed', progress?.classList.contains('failed'));
        button.classList.toggle('unavailable', !player);
        if (piece && piece.hidden !== (key !== shown)) piece.hidden = key !== shown;
      }
      const actions = section.querySelector('.backing-tools');
      const piece = flow.querySelector(`[data-piece="${shown}"]`);
      if (actions && piece) {
        const links = [...piece.querySelectorAll('a.doc, a.download')];
        const signature = shown + section.recording.backingFiles()[shown] + links.map(a => a.outerHTML).join('');
        if (signature !== toolsContent) {
          toolsContent = signature;
          const info = Object.assign(document.createElement('button'), {type: 'button', className: 'minfo', textContent: 'i'});
          info.setAttribute('aria-label', `About ${tracks[shown]}`);
          const key = shown;
          info.onclick = () => showInfo(section, key, info);
          actions.replaceChildren(info, ...links.map(a => a.cloneNode(true)));
          if (!links.length && section.recording.backingFiles()[shown]) {
            const link = document.createElement('a');
            link.href = section.recording.backingFiles()[shown];
            link.download = '';
            link.className = 'download';
            actions.append(link);
          }
          for (const link of actions.querySelectorAll('a')) {
            if (link.classList.contains('download')) {
              link.className = 'doc';
              link.title = `Download ${tracks[shown]}`;
              link.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></svg>';
            }
            link.setAttribute('aria-label', link.title);
          }
        }
      }
      draw(grid);
    }
    function schedule() {
      if (!queued) { queued = true; requestAnimationFrame(paint); }
    }
    grid.onclick = event => {
      const button = event.target.closest('[data-track]');
      if (!button) return;
      if (event.target.closest('.track-info')) {
        showInfo(section, button.dataset.track, event.target.closest('button'));
        return;
      }
      const previousKey = shown;
      shown = button.dataset.track;
      const player = media(shown);
      const play = !!event.target.closest('.track-play');
      if (player?.tagName === 'PRACTICE-AUDIO') {
        if (play && !player.paused) player.pause();
        else player.owner.requestBacking(shown, play);
      }
      else if (player) {
        const previous = [...flow.querySelectorAll(mediaSelector)].find(p => !p.paused) || media(previousKey);
        const position = previous?.currentTime ?? 0;
        if (previous && previous !== player) {
          previous.pause();
          if (player.readyState) player.currentTime = position;
          else player.addEventListener('loadedmetadata', () => { player.currentTime = position; }, {once: true});
        }
        if (play) {
          if (player.paused) player.play()?.catch?.(() => {});
          else player.pause();
        }
      }
      paint();
    };
    flow.addEventListener('play', event => {
      shown = event.target.closest('[data-piece]')?.dataset.piece || shown;
      schedule();
    }, true);
    flow.addEventListener('pause', schedule, true);
    new MutationObserver(schedule).observe(flow, {subtree: true, childList: true,
      characterData: true, attributes: true});
    new ResizeObserver(() => draw(grid)).observe(grid);
    paint();
  }
  document.addEventListener('rendered', () => {
    header();
    document.querySelectorAll('section[data-song]').forEach(decorate);
  });
  return {draw};
})();
