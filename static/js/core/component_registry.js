/**
 * Clawzd — Component Registry.
 *
 * Declarative registry for rich UI components rendered in chat responses.
 * Each component defines: detect, render, update (optional), destroy (optional).
 *
 * Instead of embedding Chart.js/Mermaid/etc logic directly in renderMd(),
 * components are registered here and the markdown renderer delegates to them.
 *
 * Usage:
 *   ComponentRegistry.register('chart', {
 *     detect: (lang) => lang === 'chart',
 *     render: (container, rawContent, id) => { ... },
 *     update: (container, rawContent, id) => { ... },
 *     destroy: (container) => { ... }
 *   });
 *
 *   // In the streaming renderer:
 *   const comp = ComponentRegistry.match('chart');
 *   if (comp) comp.render(el, content, blockId);
 */
(function () {
  'use strict';

  /** @type {Map<string, ComponentDefinition>} */
  const _components = new Map();

  /** Track active component instances for cleanup */
  const _instances = new Map();

  /**
   * @typedef {Object} ComponentDefinition
   * @property {(lang: string) => boolean} detect - Match function
   * @property {(container: HTMLElement, content: string, id: string) => void} render
   * @property {(container: HTMLElement, content: string, id: string) => void} [update]
   * @property {(container: HTMLElement) => void} [destroy]
   */

  const ComponentRegistry = {
    /**
     * Register a new component type.
     * @param {string} name - Unique component name
     * @param {ComponentDefinition} definition
     */
    register(name, definition) {
      if (!definition.detect || !definition.render) {
        console.error(`[ComponentRegistry] "${name}" must have detect() and render()`);
        return;
      }
      _components.set(name, definition);
    },

    /**
     * Find a component that matches the given language tag.
     * @param {string} lang - Code fence language (e.g., 'chart', 'mermaid')
     * @returns {ComponentDefinition|null}
     */
    match(lang) {
      for (const [, def] of _components) {
        if (def.detect(lang)) return def;
      }
      return null;
    },

    /**
     * Get a registered component by name.
     * @param {string} name
     * @returns {ComponentDefinition|null}
     */
    get(name) {
      return _components.get(name) || null;
    },

    /**
     * Render or update a component in a container.
     * If the component was already rendered with the same id, calls update().
     * @param {string} name - Component name
     * @param {HTMLElement} container
     * @param {string} content - Raw content from the code fence
     * @param {string} id - Unique block id
     */
    renderOrUpdate(name, container, content, id) {
      const def = _components.get(name);
      if (!def) return false;

      if (_instances.has(id) && def.update) {
        def.update(container, content, id);
      } else {
        def.render(container, content, id);
        _instances.set(id, { name, container });
      }
      return true;
    },

    /**
     * Destroy a component instance and clean up.
     * @param {string} id
     */
    destroyInstance(id) {
      const instance = _instances.get(id);
      if (!instance) return;
      const def = _components.get(instance.name);
      if (def && def.destroy) {
        def.destroy(instance.container);
      }
      _instances.delete(id);
    },

    /**
     * Destroy all tracked instances (e.g., on session change).
     */
    destroyAll() {
      _instances.forEach((instance, id) => {
        const def = _components.get(instance.name);
        if (def && def.destroy) def.destroy(instance.container);
      });
      _instances.clear();
    },

    /** List registered component names */
    list() {
      return [..._components.keys()];
    },

    /** Debug: show all registered components and active instances */
    debug() {
      console.group('[ComponentRegistry]');
      console.log('Registered:', [..._components.keys()]);
      console.log('Active instances:', _instances.size);
      _instances.forEach((v, k) => console.log(`  ${k} → ${v.name}`));
      console.groupEnd();
    }
  };

  window.ComponentRegistry = ComponentRegistry;
})();
