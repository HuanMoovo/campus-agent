/**
 * Project site hero: an interactive "knowledge constellation" rendered with three.js, plus the
 * three-state theme switcher (auto / light / dark).
 *
 * three.js is bundled privately under ./vendor and imported lazily once the stage is on screen,
 * so the page paints instantly and never depends on a CDN. Without WebGL, or when the visitor
 * prefers reduced motion, the stage keeps its static gradient instead.
 */
(() => {
  'use strict';

  const THEME_KEY = 'campus-agent-theme';
  const MAX_DPR = 2;
  const NODES = 7;
  const PARTICLES = 460;
  const ZOOM_RANGE = [4.0, 7.6];

  /* ---------- theme ---------- */

  const themeButtons = Array.from(document.querySelectorAll('[data-theme-choice]'));
  const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');

  function savedTheme() {
    try {
      const value = window.localStorage.getItem(THEME_KEY);
      if (value === 'light' || value === 'dark' || value === 'auto') return value;
    } catch (error) { /* private mode */ }
    return 'auto';
  }

  function effectiveTheme() {
    const choice = savedTheme();
    if (choice === 'auto') return darkQuery.matches ? 'dark' : 'light';
    return choice;
  }

  function applyTheme(choice) {
    if (choice === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', choice);
    themeButtons.forEach(button => {
      button.setAttribute('aria-pressed', button.dataset.themeChoice === choice ? 'true' : 'false');
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', effectiveTheme() === 'dark' ? '#0b1717' : '#0e7c74');
    window.dispatchEvent(new CustomEvent('mens-theme', { detail: { theme: effectiveTheme() } }));
  }

  themeButtons.forEach(button => {
    button.addEventListener('click', () => {
      const choice = button.dataset.themeChoice;
      try { window.localStorage.setItem(THEME_KEY, choice); } catch (error) { /* private mode */ }
      applyTheme(choice);
    });
  });
  darkQuery.addEventListener('change', () => { if (savedTheme() === 'auto') applyTheme('auto'); });
  applyTheme(savedTheme());

  /* ---------- scene ---------- */

  const stage = document.querySelector('.hero-stage');
  const canvas = document.querySelector('#hero-canvas');
  const hint = document.querySelector('#hero-hint');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function supportsWebGL() {
    try {
      const probe = document.createElement('canvas');
      return Boolean(probe.getContext('webgl2') || probe.getContext('webgl'));
    } catch (error) { return false; }
  }

  if (!stage || !canvas) return;
  if (!supportsWebGL()) { stage.dataset.scene = 'unsupported'; return; }

  function cssColor(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value) ? value : fallback;
  }

  async function start() {
    let THREE;
    try {
      THREE = await import('./vendor/three.module.min.js');
    } catch (error) {
      stage.dataset.scene = 'unsupported';
      console.warn('3D stage unavailable:', error);
      return;
    }

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_DPR));
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 0.35, 6.0);

    const group = new THREE.Group();
    scene.add(group);

    const accentOf = () => new THREE.Color(cssColor('--accent', '#0e7c74'));

    const coreMaterial = new THREE.MeshStandardMaterial({
      color: accentOf(), emissive: accentOf(), emissiveIntensity: 0.12,
      flatShading: true, roughness: 0.36, metalness: 0.24, transparent: true, opacity: 0.96,
    });
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(1.24, 1), coreMaterial);

    const shellMaterial = new THREE.MeshBasicMaterial({
      color: accentOf(), wireframe: true, transparent: true, opacity: 0.22,
    });
    const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(1.78, 1), shellMaterial);

    // Soft glow sprite behind the core.
    const glowCanvas = document.createElement('canvas');
    glowCanvas.width = glowCanvas.height = 256;
    const glowContext = glowCanvas.getContext('2d');
    if (glowContext) {
      const gradient = glowContext.createRadialGradient(128, 128, 0, 128, 128, 128);
      gradient.addColorStop(0, 'rgba(255,255,255,0.9)');
      gradient.addColorStop(0.34, 'rgba(255,255,255,0.28)');
      gradient.addColorStop(1, 'rgba(255,255,255,0)');
      glowContext.fillStyle = gradient;
      glowContext.fillRect(0, 0, 256, 256);
    }
    const glowTexture = new THREE.CanvasTexture(glowCanvas);
    const glowMaterial = new THREE.SpriteMaterial({
      map: glowTexture, color: accentOf(), transparent: true, opacity: 0.34,
      depthWrite: false, blending: THREE.AdditiveBlending,
    });
    const glow = new THREE.Sprite(glowMaterial);
    glow.scale.setScalar(6.6);

    // Knowledge nodes orbiting the core, each wired back to it.
    const nodeGeometry = new THREE.SphereGeometry(0.1, 18, 18);
    const nodeMaterials = [];
    const nodes = [];
    for (let index = 0; index < NODES; index += 1) {
      const material = new THREE.MeshStandardMaterial({
        color: accentOf(), emissive: accentOf(), emissiveIntensity: 0.45, roughness: 0.32, metalness: 0.1,
      });
      const mesh = new THREE.Mesh(nodeGeometry, material);
      mesh.userData = {
        radius: 2.15 + (index % 3) * 0.42,
        tilt: (index / NODES) * Math.PI * 2,
        speed: 0.32 + (index % 4) * 0.06,
        phase: (index * 0.7) % (Math.PI * 2),
      };
      nodeMaterials.push(material);
      nodes.push(mesh);
      group.add(mesh);
    }
    const linkGeometry = new THREE.BufferGeometry();
    linkGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(NODES * 6), 3));
    const linkMaterial = new THREE.LineBasicMaterial({ color: accentOf(), transparent: true, opacity: 0.28 });
    const links = new THREE.LineSegments(linkGeometry, linkMaterial);
    group.add(core, shell, glow, links);

    const positions = new Float32Array(PARTICLES * 3);
    for (let index = 0; index < PARTICLES; index += 1) {
      const radius = 2.9 + Math.random() * 2.6;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[index * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta) * 0.72;
      positions[index * 3 + 2] = radius * Math.cos(phi);
    }
    const particleGeometry = new THREE.BufferGeometry();
    particleGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const particleMaterial = new THREE.PointsMaterial({
      color: accentOf(), size: 0.045, transparent: true, opacity: 0.5, depthWrite: false, sizeAttenuation: true,
    });
    group.add(new THREE.Points(particleGeometry, particleMaterial));

    const ambient = new THREE.AmbientLight(0xffffff, 0.8);
    const key = new THREE.DirectionalLight(0xffffff, 1.3);
    key.position.set(3, 3.4, 2.8);
    const rim = new THREE.DirectionalLight(accentOf(), 0.95);
    rim.position.set(-3.2, -1.8, -2.4);
    scene.add(ambient, key, rim);

    const paint = () => {
      const dark = effectiveTheme() === 'dark';
      const surface = accentOf().lerp(new THREE.Color('#ffffff'), dark ? 0.04 : 0.1);
      coreMaterial.color.copy(surface);
      [coreMaterial, shellMaterial, linkMaterial, glowMaterial, particleMaterial].forEach(material => {
        if ('emissive' in material) material.emissive.copy(accentOf());
      });
      shellMaterial.color.copy(accentOf());
      linkMaterial.color.copy(accentOf());
      glowMaterial.color.copy(accentOf());
      particleMaterial.color.copy(accentOf());
      nodeMaterials.forEach(material => {
        material.color.copy(accentOf().lerp(new THREE.Color('#ffffff'), dark ? 0.1 : 0.16));
      });
      ambient.intensity = dark ? 0.5 : 0.84;
      key.intensity = dark ? 1.05 : 1.32;
      rim.intensity = dark ? 1.0 : 0.9;
      shellMaterial.opacity = dark ? 0.28 : 0.26;
      linkMaterial.opacity = dark ? 0.36 : 0.32;
      glowMaterial.opacity = dark ? 0.46 : 0.34;
      particleMaterial.opacity = dark ? 0.62 : 0.52;
    };
    paint();
    window.addEventListener('mens-theme', paint);

    const target = { x: 0.14, y: -0.45, zoom: 6.0 };
    const current = { x: 0.14, y: -0.45, zoom: 6.0 };
    let dragging = false;
    let pointerId = -1;
    let lastX = 0;
    let lastY = 0;
    let parallaxX = 0;
    let parallaxY = 0;

    canvas.addEventListener('pointerdown', event => {
      dragging = true;
      pointerId = event.pointerId;
      lastX = event.clientX;
      lastY = event.clientY;
      canvas.setPointerCapture(event.pointerId);
      canvas.classList.add('is-dragging');
    });
    canvas.addEventListener('pointermove', event => {
      if (dragging && event.pointerId === pointerId) {
        target.y += (event.clientX - lastX) * 0.0055;
        target.x = Math.max(-1.1, Math.min(1.1, target.x + (event.clientY - lastY) * 0.0055));
        lastX = event.clientX;
        lastY = event.clientY;
      } else if (!dragging) {
        const rect = canvas.getBoundingClientRect();
        parallaxX = ((event.clientX - rect.left) / rect.width - 0.5) * 0.34;
        parallaxY = ((event.clientY - rect.top) / rect.height - 0.5) * 0.22;
      }
    });
    const stopDrag = event => {
      if (event.pointerId !== pointerId) return;
      dragging = false;
      canvas.classList.remove('is-dragging');
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    };
    canvas.addEventListener('pointerup', stopDrag);
    canvas.addEventListener('pointercancel', stopDrag);
    canvas.addEventListener('pointerleave', () => { parallaxX = 0; parallaxY = 0; });
    canvas.addEventListener('wheel', event => {
      event.preventDefault();
      target.zoom = Math.max(ZOOM_RANGE[0], Math.min(ZOOM_RANGE[1], target.zoom + event.deltaY * 0.004));
    }, { passive: false });

    const resize = () => {
      const width = Math.max(stage.clientWidth, 1);
      const height = Math.max(stage.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    new ResizeObserver(resize).observe(stage);
    resize();

    let frame = 0;
    let running = true;
    let stamp = 0;
    const start = performance.now();
    const linkPosition = linkGeometry.getAttribute('position');
    const clock = () => (performance.now() - start) / 1000;

    const render = () => {
      if (!running) return;
      frame = requestAnimationFrame(render);
      const time = clock();
      const step = reduced ? 0 : 1;

      target.y += dragging ? 0 : 0.0024 * step;
      current.x += ((target.x + parallaxY) - current.x) * 0.07;
      current.y += ((target.y + parallaxX) - current.y) * 0.07;
      current.zoom += (target.zoom - current.zoom) * 0.12;

      group.rotation.set(current.x, current.y, 0);
      shell.rotation.y = time * 0.2 * step;
      shell.rotation.x = Math.sin(time * 0.32) * 0.12 * step;
      core.scale.setScalar(1 + Math.sin(time * 1.25) * 0.016 * step);

      nodes.forEach((mesh, index) => {
        const data = mesh.userData;
        const angle = data.tilt + time * data.speed * step;
        const x = Math.cos(angle) * data.radius;
        const y = Math.sin(angle * 1.35 + data.phase) * data.radius * 0.44;
        const z = Math.sin(angle) * data.radius;
        mesh.position.set(x, y, z);
        linkPosition.setXYZ(index * 2, x, y, z);
        linkPosition.setXYZ(index * 2 + 1, 0, 0, 0);
      });
      linkPosition.needsUpdate = true;

      camera.position.z = current.zoom;
      camera.lookAt(0, 0, 0);
      renderer.render(scene, camera);

      if (time - stamp > 0.15) {
        stamp = time;
        stage.dataset.rotation = current.x.toFixed(2) + ',' + current.y.toFixed(2);
      }
    };
    render();
    stage.dataset.scene = 'ready';
    if (hint) hint.hidden = false;

    const setRunning = next => {
      if (next === running) return;
      running = next;
      if (running) render();
      else cancelAnimationFrame(frame);
    };
    document.addEventListener('visibilitychange', () => setRunning(!document.hidden));
    new IntersectionObserver(entries => {
      entries.forEach(entry => setRunning(entry.isIntersecting && !document.hidden));
    }, { threshold: 0.05 }).observe(stage);
  }

  if (reduced) {
    // Static pose: still an interactive-looking stage, but no animation loop.
    start();
  } else {
    // Load the renderer only when the stage is about to be seen.
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        observer.disconnect();
        window.requestIdleCallback
          ? window.requestIdleCallback(() => start(), { timeout: 1200 })
          : window.setTimeout(start, 260);
      }
    }, { rootMargin: '240px' });
    observer.observe(stage);
  }
})();
