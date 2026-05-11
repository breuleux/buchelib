async function indicate(f, args, eventTarget, selector, indicatorClass = "buche-indicator") {
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
            $class: "buchelib.srx:Call",
            function: function_id,
            args: serial
        });
    }
}

document.indicate = indicate;
document.embed = embed;
