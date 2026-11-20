/* IndexedDB is isolated by origin. Each record additionally belongs to a verified
   member and game. Keep each immutable candidate until the server acknowledges
   it, including conflicts and interrupted responses. */
window.odSaveOutbox = (function () {
    let connection;
    function open() {
        if (!connection) {
            connection = new Promise((resolve, reject) => {
                const request = indexedDB.open('oneirodex-play-saves', 1);
                request.onupgradeneeded = () => {
                    request.result.createObjectStore('pending', { keyPath: 'id', autoIncrement: true })
                        .createIndex('owner', ['member', 'game']);
                };
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            }).catch(error => { connection = null; throw error; });
        }
        return connection;
    }

    async function transaction(mode, apply) {
        const db = await open();
        return new Promise((resolve, reject) => {
            const tx = db.transaction('pending', mode, { durability: mode === 'readwrite' ? 'strict' : 'default' });
            const result = apply(tx.objectStore('pending'));
            tx.oncomplete = () => resolve(result());
            tx.onabort = () => reject(tx.error || new Error('Local save storage unavailable'));
            tx.onerror = () => reject(tx.error);
        });
    }

    return {
        add(rows) {
            return transaction('readwrite', store => {
                const keys = rows.map(row => store.add(row));
                return () => rows.map((row, i) => ({ ...row, id: keys[i].result }));
            });
        },
        list(member, game) {
            return transaction('readonly', store => {
                const rows = store.index('owner').getAll([member, game]);
                return () => rows.result;
            });
        },
        remove(id) {
            return transaction('readwrite', store => {
                store.delete(id);
                return () => undefined;
            });
        }
    };
})();
