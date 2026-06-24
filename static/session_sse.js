(function(global){
  const MAX_SEEN_EVENT_IDS = 512;

  function _isObject(value){
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  function validateSessionEventEnvelope(raw){
    if(!_isObject(raw)) throw new Error('session SSE envelope must be an object');
    const required = ['schema_version','stream','session_id','event_type','event_id','sequence','ts','payload'];
    for(const key of required){
      if(!(key in raw)) throw new Error('missing session SSE field: ' + key);
    }
    if(raw.schema_version !== '1.0') throw new Error('unsupported session SSE schema_version');
    if(raw.stream !== 'session') throw new Error('unsupported session SSE stream');
    if(typeof raw.session_id !== 'string' || !raw.session_id.trim()) throw new Error('session SSE session_id must be a non-empty string');
    if(typeof raw.event_type !== 'string' || !raw.event_type.trim()) throw new Error('session SSE event_type must be a non-empty string');
    if(typeof raw.event_id !== 'string' || !raw.event_id.trim()) throw new Error('session SSE event_id must be a non-empty string');
    if(!Number.isInteger(raw.sequence) || raw.sequence < 0) throw new Error('session SSE sequence must be a non-negative integer');
    if(typeof raw.ts !== 'string' || !raw.ts.trim()) throw new Error('session SSE ts must be a non-empty string');
    if(!_isObject(raw.payload)) throw new Error('session SSE payload must be an object');
    if(raw.meta != null && !_isObject(raw.meta)) throw new Error('session SSE meta must be an object');
    return raw;
  }

  function createSessionEventTracker(options){
    const opts = options || {};
    const expectedSessionId = typeof opts.sessionId === 'string' ? opts.sessionId.trim() : '';
    const seenIds = new Map();
    let lastEventId = typeof opts.lastEventId === 'string' ? opts.lastEventId : '';
    let lastSequence = Number.isInteger(opts.lastSequence) ? opts.lastSequence : -1;

    function pruneSeenIds(){
      while(seenIds.size > MAX_SEEN_EVENT_IDS){
        const firstKey = seenIds.keys().next().value;
        if(firstKey === undefined) break;
        seenIds.delete(firstKey);
      }
    }

    function applyEnvelope(raw){
      const envelope = validateSessionEventEnvelope(raw);
      if(expectedSessionId && envelope.session_id !== expectedSessionId){
        return {status:'wrong-session', envelope};
      }
      if(seenIds.has(envelope.event_id)){
        lastEventId = envelope.event_id;
        if(envelope.sequence > lastSequence) lastSequence = envelope.sequence;
        return {status:'duplicate', envelope};
      }
      const status = envelope.sequence < lastSequence ? 'stale' : 'applied';
      seenIds.set(envelope.event_id, envelope.sequence);
      pruneSeenIds();
      lastEventId = envelope.event_id;
      if(envelope.sequence > lastSequence) lastSequence = envelope.sequence;
      return {status, envelope};
    }

    return {
      applyEnvelope,
      getLastEventId(){ return lastEventId || null; },
      getLastSequence(){ return lastSequence; }
    };
  }

  global.HermesSessionSSE = Object.freeze({
    validateSessionEventEnvelope,
    createSessionEventTracker,
  });
})(typeof window !== 'undefined' ? window : globalThis);