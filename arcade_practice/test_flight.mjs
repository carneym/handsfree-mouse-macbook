import test from 'node:test';
import assert from 'node:assert/strict';
import { Flight } from './game/flight.mjs';

test('a pilot tracking the next gate can complete a full trial with a perfect score', () => {
  const flight = new Flight();
  flight.reset({ mode:'trial', speed:28, difficulty:'relaxed' });
  for(let frame=0;frame<4000 && !flight.finished;frame++) {
    const next=flight.gates[0];
    flight.steer(next.x/8,next.y/5);
    flight.update(1/60);
  }
  assert.equal(flight.finished,true);
  assert.ok(Math.abs(flight.elapsed-60)<1e-7);
  assert.ok(flight.hits>20);
  assert.equal(flight.misses,0);
  assert.equal(flight.accuracy,100);
  assert.equal(flight.bestStreak,flight.hits);
  assert.equal(flight.gates.length,18);
});

test('misses reset the chain without ending practice and restart clears the run', () => {
  const flight=new Flight();
  flight.streak=5;
  flight.steer(-1,-1);
  for(let frame=0;frame<600;frame++)flight.update(1/60);
  assert.ok(flight.misses>0);
  assert.equal(flight.streak,0);
  assert.equal(flight.finished,false);
  flight.reset();
  assert.equal(flight.score,0);
  assert.equal(flight.distance,0);
  assert.equal(flight.misses,0);
  assert.equal(flight.accuracy,null);
});

test('stalled frames and invalid input cannot teleport or corrupt the ship', () => {
  const flight=new Flight();
  flight.steer(Infinity,NaN);
  assert.deepEqual(flight.target,{x:0,y:0});
  flight.steer(100,-100);
  assert.deepEqual(flight.target,{x:8,y:-5});
  flight.update(20);
  assert.ok(flight.distance<=flight.speed*.05);
  const before=flight.distance;
  flight.update(NaN);flight.update(-1);
  assert.equal(flight.distance,before);
});
