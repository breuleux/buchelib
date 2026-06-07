async function indicate(f, args, eventTarget, selector, indicatorClass = "buche-indicator") {
    if (!selector) {
        selector = eventTarget.getAttribute("indicator-selector") || null;
    }

    let targets;
    if (!selector) {
        targets = [eventTarget];
    } else if (selector.startsWith("closest ")) {
        const closestSelector = selector.slice(8);
        const found = eventTarget.closest(closestSelector);
        targets = found ? [found] : [];
    } else {
        targets = Array.from(document.querySelectorAll(selector));
    }

    for (const el of targets) {
        el.classList.add(indicatorClass);
    }

    try {
        return await f(...args);
    } finally {
        for (const el of targets) {
            el.classList.remove(indicatorClass);
        }
    }
}

function embed(function_id) {
    return async (...args) => {
        const serial = JSON.parse(JSON.stringify(args));
        return await window.buche.request({
            $class: "buchelib.srx:Callback",
            function: function_id,
            args: serial
        });
    }
}

Event.prototype.indicate = function(fn, ...args) {
    return indicate(fn, args, this.currentTarget || this.target);
};

window.indicate = indicate;
window.embed = embed;
